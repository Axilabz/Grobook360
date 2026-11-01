"""Inventory / Stock Ledger service (PROMPT-010).

THE STOCK LEDGER IS THE SOURCE OF TRUTH. `product.stock_qty_cache` is a
read-optimization that is ONLY ever written here, in the same DB
transaction as the ledger insert that justifies the change (FR-STK-05).

Every future module (Sales, Purchase, Returns) that needs to move stock
must call `post_movement` (or a thin wrapper around it) rather than
inventing its own stock arithmetic — this is the "reusable stock movement
service" §38 asks for.

PROMPT-011 (Sales & Billing Foundation) formalizes this as the actual
Sales-to-Inventory integration contract: a future Delivery Challan or
direct Sales Invoice posting calls `post_movement(movement_type=STOCK_OUT,
source_type="DELIVERY_CHALLAN"/"SALES_INVOICE", source_id=<that
document's id>, ...)` inside its own DB transaction; a Sales Return calls
it with `movement_type=STOCK_IN, source_type="SALES_RETURN"`. No new
migration was needed — STOCK_IN/STOCK_OUT already exist in
`ck_stock_ledger_entry_movement_type` (PROMPT-010); only `source_type`
varies per caller. Preventing a double stock-out when an Invoice is
generated from an already-posted Delivery Challan (§28) is that future
Sales Invoice prompt's own responsibility to check before calling this
method (e.g. by recording and inspecting the DC-to-Invoice conversion
link) — this service has no way to know that relationship exists.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    INV_DUPLICATE_OPENING_STOCK,
    INV_INACTIVE_PRODUCT,
    INV_INSUFFICIENT_STOCK,
    INV_INVALID_UOM,
    INV_NOT_FOUND,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.location import Location
from app.models.product import Product
from app.models.product_unit_conversion import ProductUnitConversion
from app.models.stock_adjustment import StockAdjustment
from app.models.stock_ledger_entry import (
    ADJUSTMENT_IN,
    ADJUSTMENT_OUT,
    MOVEMENT_DIRECTION,
    OPENING_STOCK,
    STOCK_IN,
    STOCK_OUT,
    StockLedgerEntry,
)
from app.models.unit_of_measure import UnitOfMeasure
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService

_MAX_NUMBER_ATTEMPTS = 5
_DEFAULT_LOCATION_CODE = "MAIN"


@dataclass(frozen=True)
class InventoryPage:
    items: list[tuple[Product, UnitOfMeasure, Decimal | None]]  # (product, base_uom, last_movement_at)
    total_items: int


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared lookups ---------------------------------------------------

    async def ensure_default_location(self, tenant_id: uuid.UUID) -> Location:
        # §8: M1 supports exactly one active location. No management API
        # exists — lazily get-or-create it rather than requiring a setup
        # screen nothing in this prompt's scope asks for.
        result = await self._session.execute(
            select(Location).where(Location.tenant_id == tenant_id, Location.code == _DEFAULT_LOCATION_CODE)
        )
        location = result.scalar_one_or_none()
        if location is None:
            location = Location(tenant_id=tenant_id, code=_DEFAULT_LOCATION_CODE, name="Main Location")
            self._session.add(location)
            await self._session.flush()
        return location

    async def _get_active_product_locked(self, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product:
        # FOR UPDATE: serializes concurrent movements on the same product so
        # "check available, then update" cannot race (§40).
        result = await self._session.execute(
            select(Product)
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
            .with_for_update()
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise NotFoundError("Product not found", code=INV_NOT_FOUND)
        if product.status != "ACTIVE":
            raise ValidationAppError(
                "This product is inactive and cannot be used for this operation.", code=INV_INACTIVE_PRODUCT
            )
        return product

    async def get_active_product_locked(self, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product:
        """Public entrypoint for PROMPT-014's DeliveryChallanService — locks
        the product row (§20 stock concurrency) before calling
        `post_movement`, exactly like every in-module caller already does."""
        return await self._get_active_product_locked(tenant_id, product_id)

    async def get_uom_or_raise(self, tenant_id: uuid.UUID, uom_id: uuid.UUID) -> UnitOfMeasure:
        result = await self._session.execute(
            select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id, UnitOfMeasure.tenant_id == tenant_id)
        )
        unit = result.scalar_one_or_none()
        if unit is None:
            raise ValidationAppError("Select a valid unit.", code=INV_INVALID_UOM)
        return unit

    async def _conversion_factor(self, tenant_id: uuid.UUID, product: Product, uom: UnitOfMeasure) -> Decimal:
        if uom.id == product.base_uom_id:
            return Decimal("1")
        result = await self._session.execute(
            select(ProductUnitConversion).where(
                ProductUnitConversion.tenant_id == tenant_id,
                ProductUnitConversion.product_id == product.id,
                ProductUnitConversion.from_uom_id == uom.id,
                ProductUnitConversion.to_uom_id == product.base_uom_id,
            )
        )
        conversion = result.scalar_one_or_none()
        if conversion is None:
            # §19/§53: no automatic reverse-derivation of conversions (open
            # decision, see PROMPT-010-NOTES.md) — the exact from->to
            # direction must already be defined on the product.
            raise ValidationAppError("Unable to convert the selected unit.", code=INV_INVALID_UOM)
        return conversion.conversion_factor

    # --- core movement primitive -------------------------------------------

    async def post_movement(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product: Product,
        location: Location,
        movement_type: str,
        quantity: Decimal,
        uom: UnitOfMeasure,
        source_type: str,
        source_id: uuid.UUID,
        audit_action: str,
        audit_extra: dict | None,
        ip_address: str | None,
        unit_cost: Decimal | None = None,
    ) -> StockLedgerEntry:
        # `unit_cost` is optional and additive — every existing caller
        # (Delivery Challan, Goods Receipt, Sales/Purchase Invoice, Sales/
        # Purchase Return, ...) omits it and the column stays NULL, exactly
        # as before this parameter existed. Only InventoryService's own 4
        # manual-movement methods pass it, to value a journal entry at
        # Weighted Average Cost. Must be set HERE, at insert time — the
        # trigger below makes any later UPDATE to this row impossible.
        factor = await self._conversion_factor(tenant_id, product, uom)
        base_quantity = (quantity * factor).quantize(Decimal("0.001"))
        direction = MOVEMENT_DIRECTION[movement_type]

        new_balance = product.stock_qty_cache + (direction * base_quantity)
        if new_balance < 0:
            # §18/§52: negative stock prohibited (OQ-008 resolved this way —
            # see PROMPT-010-NOTES.md). Available shown in the product's
            # base unit, since that's what the cache/ledger actually track.
            raise ConflictError(
                f"Insufficient stock. Available quantity: {product.stock_qty_cache}.",
                code=INV_INSUFFICIENT_STOCK,
            )

        entry = StockLedgerEntry(
            tenant_id=tenant_id,
            product_id=product.id,
            location_id=location.id,
            source_type=source_type,
            source_id=source_id,
            movement_type=movement_type,
            quantity=quantity,
            uom_id=uom.id,
            base_quantity=base_quantity,
            unit_cost=unit_cost,
            occurred_at=datetime.now(timezone.utc),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        async with self._session.begin_nested():
            self._session.add(entry)
            product.stock_qty_cache = new_balance
            product.updated_by = actor_user_id
            await self._session.flush()

        after = {
            "movement_type": movement_type,
            "quantity": str(quantity),
            "uom": uom.code,
            "base_quantity": str(base_quantity),
            "resulting_balance": str(new_balance),
        }
        if audit_extra:
            after.update(audit_extra)

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=audit_action,
            entity_type="stock_ledger_entry",
            entity_id=entry.id,
            after=after,
            ip_address=ip_address,
        )
        return entry

    # --- opening stock -------------------------------------------------

    async def record_opening_stock(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        uom_id: uuid.UUID,
        unit_cost: Decimal | None = None,
        ip_address: str | None,
    ) -> StockLedgerEntry:
        product = await self._get_active_product_locked(tenant_id, product_id)
        uom = await self.get_uom_or_raise(tenant_id, uom_id)
        location = await self.ensure_default_location(tenant_id)

        # unit_cost must be passed INTO post_movement so it's part of the
        # initial INSERT — stock_ledger_entry is append-only (migration
        # 0011's BEFORE UPDATE/DELETE trigger rejects any later UPDATE, the
        # same discipline as audit_log), so it can never be set afterward.
        try:
            entry = await self.post_movement(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                product=product,
                location=location,
                movement_type=OPENING_STOCK,
                quantity=quantity,
                uom=uom,
                # source_id = product_id: at most one opening-stock entry can
                # ever exist per product (DB unique constraint enforces it —
                # §20's recommended principle, §68 Q9 resolved as "no").
                source_type="OPENING_STOCK",
                source_id=product.id,
                audit_action="OPENING_STOCK_CREATED",
                audit_extra=None,
                ip_address=ip_address,
                unit_cost=unit_cost,
            )
        except IntegrityError as exc:
            raise ConflictError(
                "Opening stock has already been recorded for this product.", code=INV_DUPLICATE_OPENING_STOCK
            ) from exc

        # Manual Stock Movements -> Accounting (Weighted Average Cost): the
        # entered unit_cost (always per the product's BASE unit, same
        # denomination as the existing Product.cost_price field) becomes the
        # product's starting cost basis outright -- opening stock defines the
        # baseline, nothing to blend against yet. Omitting unit_cost still
        # records the stock movement fine; it just posts no journal (never a
        # fabricated/zero-value entry).
        if unit_cost is not None and unit_cost > 0:
            product.cost_price = unit_cost
            amount = (entry.base_quantity * unit_cost).quantize(Decimal("0.01"))
            await self._session.flush()
            await AccountingPostingService(self._session).post_opening_stock(
                tenant_id=tenant_id, actor_user_id=actor_user_id, source_id=entry.id,
                movement_date=entry.occurred_at.date(), amount=amount,
                description=f"Opening stock — {product.sku}", ip_address=ip_address,
            )
        return entry

    # --- manual stock-in / stock-out (§16/§17: the foundation future
    # Purchase/Sales modules will call internally with their own
    # source_type once built) ------------------------------------------

    async def record_stock_in(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        uom_id: uuid.UUID,
        notes: str | None,
        unit_cost: Decimal | None = None,
        ip_address: str | None,
    ) -> StockLedgerEntry:
        product = await self._get_active_product_locked(tenant_id, product_id)
        uom = await self.get_uom_or_raise(tenant_id, uom_id)
        location = await self.ensure_default_location(tenant_id)
        qty_before = product.stock_qty_cache
        avg_before = product.cost_price
        # Manual Stock Movements -> Accounting (Weighted Average Cost):
        # unit_cost given -> recompute the running average and post using
        # the entered cost. unit_cost omitted -> fall back to the CURRENT
        # average (assumes this correction is worth the same as existing
        # stock) so the average itself is left unchanged. Resolved BEFORE
        # post_movement so it can be passed in and stored at insert time —
        # stock_ledger_entry is append-only (migration 0011's trigger
        # rejects any later UPDATE).
        cost_used = unit_cost if unit_cost is not None else avg_before

        entry = await self.post_movement(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product=product,
            location=location,
            movement_type=STOCK_IN,
            quantity=quantity,
            uom=uom,
            source_type="MANUAL_STOCK_IN",
            source_id=uuid.uuid4(),
            audit_action="STOCK_MOVEMENT_CREATED",
            audit_extra={"notes": notes} if notes else None,
            ip_address=ip_address,
            unit_cost=cost_used if cost_used else None,
        )

        amount = (entry.base_quantity * cost_used).quantize(Decimal("0.01")) if cost_used else Decimal("0")
        if unit_cost is not None and unit_cost > 0:
            new_qty = qty_before + entry.base_quantity
            product.cost_price = ((qty_before * avg_before) + (entry.base_quantity * unit_cost)) / new_qty
        await self._session.flush()
        description = f"Manual Stock In — {product.sku}" + (f" ({notes})" if notes else "")
        await AccountingPostingService(self._session).post_stock_increase(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type="MANUAL_STOCK_IN", source_id=entry.id,
            movement_date=entry.occurred_at.date(), amount=amount, description=description, ip_address=ip_address,
        )
        return entry

    async def record_stock_out(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        uom_id: uuid.UUID,
        notes: str | None,
        ip_address: str | None,
    ) -> StockLedgerEntry:
        product = await self._get_active_product_locked(tenant_id, product_id)
        uom = await self.get_uom_or_raise(tenant_id, uom_id)
        location = await self.ensure_default_location(tenant_id)
        # Weighted-average cost never changes on an outflow -- only the
        # quantity decreases; the per-unit cost of what remains is unaffected.
        cost_used = product.cost_price

        entry = await self.post_movement(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product=product,
            location=location,
            movement_type=STOCK_OUT,
            quantity=quantity,
            uom=uom,
            source_type="MANUAL_STOCK_OUT",
            source_id=uuid.uuid4(),
            audit_action="STOCK_MOVEMENT_CREATED",
            audit_extra={"notes": notes} if notes else None,
            ip_address=ip_address,
            unit_cost=cost_used if cost_used else None,
        )

        amount = (entry.base_quantity * cost_used).quantize(Decimal("0.01")) if cost_used else Decimal("0")
        description = f"Manual Stock Out — {product.sku}" + (f" ({notes})" if notes else "")
        await AccountingPostingService(self._session).post_stock_decrease(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type="MANUAL_STOCK_OUT", source_id=entry.id,
            movement_date=entry.occurred_at.date(), amount=amount, description=description, ip_address=ip_address,
        )
        return entry

    # --- manual stock adjustment -----------------------------------------

    async def _next_adjustment_number(self, tenant_id: uuid.UUID, attempt: int) -> str:
        count_stmt = select(func.count(StockAdjustment.id)).where(StockAdjustment.tenant_id == tenant_id)
        count = (await self._session.execute(count_stmt)).scalar_one()
        return f"ADJ-{count + 1 + attempt:04d}"

    async def record_adjustment(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        uom_id: uuid.UUID,
        direction: str,
        reason: str,
        unit_cost: Decimal | None = None,
        ip_address: str | None,
    ) -> tuple[StockLedgerEntry, StockAdjustment]:
        product = await self._get_active_product_locked(tenant_id, product_id)
        uom = await self.get_uom_or_raise(tenant_id, uom_id)
        location = await self.ensure_default_location(tenant_id)
        movement_type = ADJUSTMENT_IN if direction == "IN" else ADJUSTMENT_OUT
        qty_before = product.stock_qty_cache
        avg_before = product.cost_price

        last_error: Exception | None = None
        for attempt in range(_MAX_NUMBER_ATTEMPTS):
            number = await self._next_adjustment_number(tenant_id, attempt)
            adjustment = StockAdjustment(
                tenant_id=tenant_id,
                adjustment_number=number,
                location_id=location.id,
                reason=reason,
                # Self-approved atomically — see model/migration docstring:
                # no source defines a reviewer role distinct from the
                # Owner/Manager authority that already gates this endpoint.
                status="APPROVED",
                approved_by=actor_user_id,
                approved_at=datetime.now(timezone.utc),
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(adjustment)
                    await self._session.flush()
                break
            except IntegrityError as exc:
                last_error = exc
                continue
        else:
            raise ConflictError("Could not allocate a unique adjustment number. Please retry.") from last_error

        # Manual Stock Movements -> Accounting (Weighted Average Cost) --
        # mirrors record_stock_in/record_stock_out's own resolution exactly,
        # branching on the adjustment's own direction. Resolved BEFORE
        # post_movement so it can be passed in and stored at insert time —
        # stock_ledger_entry is append-only (migration 0011's trigger
        # rejects any later UPDATE).
        cost_used = (unit_cost if unit_cost is not None else avg_before) if direction == "IN" else avg_before

        entry = await self.post_movement(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product=product,
            location=location,
            movement_type=movement_type,
            quantity=quantity,
            uom=uom,
            source_type="STOCK_ADJUSTMENT",
            source_id=adjustment.id,
            audit_action="STOCK_ADJUSTMENT_CREATED",
            audit_extra={"adjustment_number": number, "reason": reason, "direction": direction},
            ip_address=ip_address,
            unit_cost=cost_used if cost_used else None,
        )

        description = f"Stock Adjustment {adjustment.adjustment_number} — {reason}"
        posting_service = AccountingPostingService(self._session)
        if direction == "IN":
            amount = (entry.base_quantity * cost_used).quantize(Decimal("0.01")) if cost_used else Decimal("0")
            if unit_cost is not None and unit_cost > 0:
                new_qty = qty_before + entry.base_quantity
                product.cost_price = ((qty_before * avg_before) + (entry.base_quantity * unit_cost)) / new_qty
            await self._session.flush()
            await posting_service.post_stock_increase(
                tenant_id=tenant_id, actor_user_id=actor_user_id, source_type="STOCK_ADJUSTMENT", source_id=entry.id,
                movement_date=entry.occurred_at.date(), amount=amount, description=description, ip_address=ip_address,
            )
        else:
            amount = (entry.base_quantity * cost_used).quantize(Decimal("0.01")) if cost_used else Decimal("0")
            await posting_service.post_stock_decrease(
                tenant_id=tenant_id, actor_user_id=actor_user_id, source_type="STOCK_ADJUSTMENT", source_id=entry.id,
                movement_date=entry.occurred_at.date(), amount=amount, description=description, ip_address=ip_address,
            )
        return entry, adjustment

    # --- queries -----------------------------------------------------------

    async def get_availability(self, *, tenant_id: uuid.UUID, product_id: uuid.UUID) -> tuple[Product, UnitOfMeasure]:
        result = await self._session.execute(
            select(Product, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_uom_id)
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Product not found", code=INV_NOT_FOUND)
        return row[0], row[1]

    async def list_inventory(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        stock_status: str | None,
    ) -> InventoryPage:
        last_movement_subq = (
            select(StockLedgerEntry.product_id, func.max(StockLedgerEntry.occurred_at).label("last_movement_at"))
            .where(StockLedgerEntry.tenant_id == tenant_id)
            .group_by(StockLedgerEntry.product_id)
            .subquery()
        )

        base = (
            select(Product, UnitOfMeasure, last_movement_subq.c.last_movement_at)
            .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_uom_id)
            .outerjoin(last_movement_subq, last_movement_subq.c.product_id == Product.id)
            .where(Product.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
        if stock_status == "zero_stock":
            base = base.where(Product.stock_qty_cache == 0)
        elif stock_status == "in_stock":
            base = base.where(Product.stock_qty_cache > 0)
        elif stock_status == "low_stock":
            # BRULE-DASH-01 (Confirmed): Low Stock = current stock <=
            # reorder level, evaluated at read time.
            base = base.where(Product.reorder_level > 0, Product.stock_qty_cache <= Product.reorder_level)

        count_stmt = select(func.count()).select_from(base.with_only_columns(Product.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(Product.name).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return InventoryPage(items=[(row[0], row[1], row[2]) for row in rows], total_items=total_items)

    async def list_movements(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        page: int,
        page_size: int,
        movement_type: str | None,
    ) -> tuple[list[tuple[StockLedgerEntry, UnitOfMeasure, Decimal]], int]:
        # Product existence/tenant-ownership check (404 parity with other
        # modules) before exposing any movement data.
        await self.get_availability(tenant_id=tenant_id, product_id=product_id)

        stmt = (
            select(StockLedgerEntry, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == StockLedgerEntry.uom_id)
            .where(StockLedgerEntry.tenant_id == tenant_id, StockLedgerEntry.product_id == product_id)
        )
        if movement_type:
            stmt = stmt.where(StockLedgerEntry.movement_type == movement_type)
        # Ordering rule (§36, resolved): occurred_at, tie-broken by created_at
        # then id, oldest first — used to compute a deterministic running
        # balance from the authoritative ledger sequence.
        stmt = stmt.order_by(StockLedgerEntry.occurred_at, StockLedgerEntry.created_at, StockLedgerEntry.id)

        rows = (await self._session.execute(stmt)).all()

        running = Decimal("0")
        enriched: list[tuple[StockLedgerEntry, UnitOfMeasure, Decimal]] = []
        for entry, uom in rows:
            running += MOVEMENT_DIRECTION[entry.movement_type] * entry.base_quantity
            enriched.append((entry, uom, running))

        total_items = len(enriched)
        enriched.reverse()  # most recent first for display
        start = (page - 1) * page_size
        page_items = enriched[start : start + page_size]

        return page_items, total_items
