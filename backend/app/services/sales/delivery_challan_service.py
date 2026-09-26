"""Delivery Challan service (PROMPT-014).

The FIRST Sales document type that actually moves stock. §3 is a
MANDATORY business rule: DRAFT never touches inventory; CONFIRMED creates
exactly one Stock OUT movement per line, atomically with the status
change and the source Sales Order's fulfillment update — all three
succeed together or none of them do (§17).

Traceability chain (§37): DeliveryChallan -> DeliveryChallanLine ->
StockLedgerEntry (via `source_type='DELIVERY_CHALLAN'`,
`source_id=<delivery_challan_line.id>`) -> Product; and separately
DeliveryChallan.source_sales_order_id -> SalesOrder ->
SalesOrderLine.delivered_quantity.

Why `source_id` is the LINE's id, not the header's: `stock_ledger_entry`'s
existing `uq_stock_ledger_entry_source (tenant_id, source_type,
source_id)` constraint (PROMPT-010, migration 0011) allows at most ONE
ledger row per `(source_type, source_id)` pair. A multi-line Delivery
Challan needs one Stock OUT per line, so the header's own id can't be
`source_id` for more than one of them — the line's id is the natural
per-movement-unique key, and this constraint is exactly the duplicate-
movement protection §18/§34 ask for (a retried confirm that already
inserted a line's movement will hit this constraint on retry, though the
Idempotency-Key check at the API layer is expected to short-circuit
before that in the normal case).

Never touches inventory except through `InventoryService.post_movement` —
no direct `product.stock_qty_cache` writes here, matching the same
discipline `sales_order_service.py` documents for its OWN (never) use of
that service.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    DC_EXCEEDS_REMAINING,
    DC_INVALID_QUANTITY,
    DC_INVALID_STATUS,
    DC_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.sales_constants import DELIVERY_CHALLAN
from app.models.customer import Customer
from app.models.delivery_challan import CANCELLABLE_STATUSES, CANCELLED, CONFIRMED, DRAFT, DeliveryChallan
from app.models.delivery_challan_line import DeliveryChallanLine
from app.models.sales_order import DELIVERY_ELIGIBLE_STATUSES, SalesOrder
from app.models.sales_order_line import SalesOrderLine
from app.models.stock_ledger_entry import STOCK_OUT
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.models.user import User
from app.schemas.delivery_challan import DeliveryLineInput
from app.services.audit.audit_service import AuditService
from app.services.inventory.inventory_service import InventoryService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.sales_order_service import SalesOrderService
from app.services.sales.sales_validation_service import (
    validate_customer_for_sale,
    validate_product_for_sale,
)


@dataclass(frozen=True)
class DeliveryChallanPage:
    items: list[tuple[DeliveryChallan, str, str, str | None, str | None]]  # (challan, customer_name, so_number, created_by_name, updated_by_name)
    total_items: int


@dataclass(frozen=True)
class EligibilityLine:
    sales_order_line: SalesOrderLine
    uom: UnitOfMeasure
    delivered_quantity: Decimal
    remaining_quantity: Decimal


class DeliveryChallanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_challan_locked(self, tenant_id: uuid.UUID, challan_id: uuid.UUID) -> DeliveryChallan:
        result = await self._session.execute(
            select(DeliveryChallan)
            .where(DeliveryChallan.id == challan_id, DeliveryChallan.tenant_id == tenant_id)
            .with_for_update()
        )
        challan = result.scalar_one_or_none()
        if challan is None:
            raise NotFoundError("Delivery challan not found", code=DC_NOT_FOUND)
        return challan

    async def _get_lines(self, challan_id: uuid.UUID) -> list[tuple[DeliveryChallanLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(DeliveryChallanLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == DeliveryChallanLine.uom_id)
            .where(DeliveryChallanLine.challan_id == challan_id)
            .order_by(DeliveryChallanLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- public entrypoints for PROMPT-015's SalesInvoiceService ------------

    async def get_challan_locked(self, tenant_id: uuid.UUID, challan_id: uuid.UUID) -> DeliveryChallan:
        """Locks the Delivery Challan row so two concurrent invoice
        postings against the same challan serialize instead of racing
        (§16/§38 of PROMPT-015) — the exact same pattern
        `SalesOrderService.get_order_locked` already established for
        Delivery Challan's own confirm-time concurrency guarantee."""
        return await self._get_challan_locked(tenant_id, challan_id)

    async def get_lines(self, challan_id: uuid.UUID) -> list[tuple[DeliveryChallanLine, UnitOfMeasure]]:
        return await self._get_lines(challan_id)

    def _snapshot(self, challan: DeliveryChallan) -> dict:
        return {
            "source_sales_order_id": str(challan.source_sales_order_id),
            "customer_id": str(challan.customer_id),
            "challan_date": challan.challan_date.isoformat(),
            "status": challan.status,
            "total_quantity": str(challan.total_quantity),
        }

    # --- delivery eligibility (§12 steps 4-7 / §31 suggested endpoint) -----

    async def get_delivery_eligibility(
        self, *, tenant_id: uuid.UUID, sales_order_id: uuid.UUID
    ) -> tuple[SalesOrder, str, list[EligibilityLine]]:
        so_service = SalesOrderService(self._session)
        order, customer_name, _created_by_name, _updated_by_name, lines = await so_service.get_order(tenant_id=tenant_id, order_id=sales_order_id)

        if order.status not in DELIVERY_ELIGIBLE_STATUSES:
            raise ValidationAppError(
                f"A sales order in {order.status} status is not eligible for delivery.",
                code=DC_INVALID_STATUS,
            )

        eligibility_lines = [
            EligibilityLine(
                sales_order_line=line,
                uom=uom,
                delivered_quantity=line.delivered_quantity,
                remaining_quantity=line.quantity - line.delivered_quantity,
            )
            for line, uom in lines
        ]
        return order, customer_name, eligibility_lines

    # --- queries ---------------------------------------------------------

    async def list_challans(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        status_filter: str | None,
        customer_id: uuid.UUID | None,
        sales_order_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> DeliveryChallanPage:
        creator = aliased(User)
        updater = aliased(User)
        base = (
            select(DeliveryChallan, Customer.name, SalesOrder.order_number, creator.name, updater.name)
            .join(Customer, Customer.id == DeliveryChallan.customer_id)
            .join(SalesOrder, SalesOrder.id == DeliveryChallan.source_sales_order_id)
            .outerjoin(creator, creator.id == DeliveryChallan.created_by)
            .outerjoin(updater, updater.id == DeliveryChallan.updated_by)
            .where(DeliveryChallan.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    DeliveryChallan.challan_number.ilike(like),
                    SalesOrder.order_number.ilike(like),
                    Customer.name.ilike(like),
                    Customer.customer_code.ilike(like),
                )
            )
        if status_filter:
            base = base.where(DeliveryChallan.status == status_filter)
        if customer_id:
            base = base.where(DeliveryChallan.customer_id == customer_id)
        if sales_order_id:
            base = base.where(DeliveryChallan.source_sales_order_id == sales_order_id)
        if date_from:
            base = base.where(DeliveryChallan.challan_date >= date_from)
        if date_to:
            base = base.where(DeliveryChallan.challan_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(DeliveryChallan.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(DeliveryChallan.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return DeliveryChallanPage(items=[(row[0], row[1], row[2], row[3], row[4]) for row in rows], total_items=total_items)

    async def get_challan(
        self, *, tenant_id: uuid.UUID, challan_id: uuid.UUID
    ) -> tuple[DeliveryChallan, str, str, str | None, str | None, list[tuple[DeliveryChallanLine, UnitOfMeasure]]]:
        creator = aliased(User)
        updater = aliased(User)
        result = await self._session.execute(
            select(DeliveryChallan, Customer.name, SalesOrder.order_number, creator.name, updater.name)
            .join(Customer, Customer.id == DeliveryChallan.customer_id)
            .join(SalesOrder, SalesOrder.id == DeliveryChallan.source_sales_order_id)
            .outerjoin(creator, creator.id == DeliveryChallan.created_by)
            .outerjoin(updater, updater.id == DeliveryChallan.updated_by)
            .where(DeliveryChallan.id == challan_id, DeliveryChallan.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Delivery challan not found", code=DC_NOT_FOUND)
        challan, customer_name, so_number, created_by_name, updated_by_name = row
        lines = await self._get_lines(challan.id)
        return challan, customer_name, so_number, created_by_name, updated_by_name, lines

    # --- line building (shared by create/update) ----------------------------

    async def _build_lines(
        self,
        *,
        tenant_id: uuid.UUID,
        challan_id: uuid.UUID,
        order: SalesOrder,
        line_inputs: list[DeliveryLineInput],
    ) -> tuple[list[DeliveryChallanLine], Decimal]:
        """§13: validates each requested delivery quantity against the
        CURRENTLY-known remaining quantity (ordered - delivered_quantity).
        This is a DRAFT-time convenience check only — the authoritative,
        race-proof re-validation happens again in `confirm_challan` under
        a lock (§19/§20), since a DRAFT by definition hasn't reserved
        anything yet."""
        so_service = SalesOrderService(self._session)
        so_lines = await so_service.get_lines(order.id)
        so_lines_by_id = {line.id: (line, uom) for line, uom in so_lines}

        lines: list[DeliveryChallanLine] = []
        total_quantity = Decimal("0")

        for index, line_input in enumerate(line_inputs, start=1):
            so_line_id = uuid.UUID(line_input.sales_order_line_id)
            match = so_lines_by_id.get(so_line_id)
            if match is None:
                raise ValidationAppError(
                    "The selected sales order line does not belong to this sales order.",
                    code=DC_INVALID_QUANTITY,
                )
            so_line, uom = match

            if so_line.product_id is not None:
                validated_product = await validate_product_for_sale(
                    self._session, tenant_id=tenant_id, product_id=so_line.product_id
                )
                product = validated_product.product
            else:
                product = None

            remaining = so_line.quantity - so_line.delivered_quantity
            if line_input.quantity > remaining:
                raise ValidationAppError(
                    f"Delivery quantity {line_input.quantity} exceeds remaining quantity {remaining}.",
                    code=DC_EXCEEDS_REMAINING,
                )

            total_quantity += line_input.quantity
            lines.append(
                DeliveryChallanLine(
                    tenant_id=tenant_id,
                    challan_id=challan_id,
                    line_no=index,
                    source_sales_order_line_id=so_line.id,
                    product_id=so_line.product_id,
                    description=so_line.description,
                    hsn_code=so_line.hsn_code,
                    uom_id=uom.id,
                    ordered_quantity=so_line.quantity,
                    previously_delivered_quantity=so_line.delivered_quantity,
                    current_delivery_quantity=line_input.quantity,
                    remaining_quantity=remaining - line_input.quantity,
                )
            )

        return lines, total_quantity

    # --- create / update (DRAFT only) ---------------------------------------

    async def create_challan(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        sales_order_id: uuid.UUID,
        challan_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[DeliveryLineInput],
        ip_address: str | None,
    ) -> tuple[DeliveryChallan, str, str, list[tuple[DeliveryChallanLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        so_service = SalesOrderService(self._session)
        order, _customer_name, _created_by_name, _updated_by_name, _lines = await so_service.get_order(tenant_id=tenant_id, order_id=sales_order_id)

        if order.status not in DELIVERY_ELIGIBLE_STATUSES:
            raise ValidationAppError(
                f"A sales order in {order.status} status is not eligible for delivery.",
                code=DC_INVALID_STATUS,
            )

        validated_customer = await validate_customer_for_sale(
            self._session, tenant_id=tenant_id, customer_id=order.customer_id
        )
        customer = validated_customer.customer

        doc_date = challan_date or date.today()
        numbering = DocumentNumberingService(self._session)
        challan_number = await numbering.next_number(tenant=tenant, document_type=DELIVERY_CHALLAN, prefix="DC")

        challan = DeliveryChallan(
            tenant_id=tenant_id,
            challan_number=challan_number,
            challan_date=doc_date,
            source_sales_order_id=order.id,
            customer_id=customer.id,
            status=DRAFT,
            billing_address=order.billing_address,
            shipping_address=shipping_address or order.shipping_address,
            place_of_supply_state_code=order.place_of_supply_state_code,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(challan)
        await self._session.flush()

        lines, total_quantity = await self._build_lines(
            tenant_id=tenant_id, challan_id=challan.id, order=order, line_inputs=line_inputs
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        challan.total_quantity = total_quantity
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="DELIVERY_CHALLAN_CREATED",
            entity_type="delivery_challan",
            entity_id=challan.id,
            after=self._snapshot(challan),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(challan.id)
        return challan, customer.name, order.order_number, lines_with_uom

    async def update_challan(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        challan_id: uuid.UUID,
        expected_row_version: int,
        challan_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[DeliveryLineInput] | None,
        ip_address: str | None,
    ) -> tuple[DeliveryChallan, str, str, list[tuple[DeliveryChallanLine, UnitOfMeasure]]]:
        challan = await self._get_challan_locked(tenant_id, challan_id)
        check_row_version(challan, expected_row_version)

        if challan.status != DRAFT:
            raise ValidationAppError(
                "This delivery challan has already been confirmed and cannot be edited.", code=DC_INVALID_STATUS
            )

        before = self._snapshot(challan)

        if challan_date is not None:
            challan.challan_date = challan_date
        if shipping_address is not None:
            challan.shipping_address = shipping_address
        if notes is not None:
            challan.notes = notes

        so_service = SalesOrderService(self._session)
        order, customer_name, _created_by_name, _updated_by_name, _lines = await so_service.get_order(
            tenant_id=tenant_id, order_id=challan.source_sales_order_id
        )

        if line_inputs is not None:
            existing_lines = await self._get_lines(challan.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, total_quantity = await self._build_lines(
                tenant_id=tenant_id, challan_id=challan.id, order=order, line_inputs=line_inputs
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)
            challan.total_quantity = total_quantity

        challan.updated_by = actor_user_id
        challan.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="DELIVERY_CHALLAN_UPDATED",
            entity_type="delivery_challan",
            entity_id=challan.id,
            before=before,
            after=self._snapshot(challan),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(challan.id)
        return challan, customer_name, order.order_number, lines_with_uom

    # --- confirm (§3/§17/§22: the atomic stock-out + fulfillment core) ------

    async def confirm_challan(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        challan_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[DeliveryChallan, str, str, list[tuple[DeliveryChallanLine, UnitOfMeasure]]]:
        """One database transaction end-to-end (§17): validate -> lock
        source Sales Order -> re-validate remaining quantity against LIVE
        data -> post Stock OUT per line -> update Sales Order fulfillment
        -> mark CONFIRMED -> audit. Any failure anywhere rolls back
        everything (no partial completion, same session/commit-at-router
        pattern already relied on by `SalesOrderService.create_from_estimate`).
        """
        challan = await self._get_challan_locked(tenant_id, challan_id)
        check_row_version(challan, expected_row_version)

        if challan.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a delivery challan in {challan.status} status.", code=DC_INVALID_STATUS)

        so_service = SalesOrderService(self._session)
        # §19/§20: locks the Sales Order row so a concurrent confirm of a
        # DIFFERENT Delivery Challan against the SAME order cannot race —
        # the second transaction blocks here until the first fully commits.
        order = await so_service.get_order_locked(tenant_id, challan.source_sales_order_id)
        if order.status not in DELIVERY_ELIGIBLE_STATUSES:
            raise ValidationAppError(
                f"The source sales order is in {order.status} status and can no longer be delivered against.",
                code=DC_INVALID_STATUS,
            )

        # Fresh read, post-lock: sees any delivered_quantity change already
        # committed by a concurrent Delivery Challan confirmation.
        so_lines = await so_service.get_lines(order.id)
        so_lines_by_id = {line.id: (line, uom) for line, uom in so_lines}

        challan_lines = await self._get_lines(challan.id)
        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)
        line_deliveries: dict[uuid.UUID, Decimal] = {}

        for dc_line, dc_uom in challan_lines:
            match = so_lines_by_id.get(dc_line.source_sales_order_line_id)
            if match is None:
                raise ValidationAppError("The source sales order line no longer exists.", code=DC_INVALID_QUANTITY)
            so_line, _so_uom = match

            live_remaining = so_line.quantity - so_line.delivered_quantity
            if dc_line.current_delivery_quantity > live_remaining:
                raise ValidationAppError(
                    f"Delivery quantity {dc_line.current_delivery_quantity} exceeds remaining "
                    f"quantity {live_remaining}.",
                    code=DC_EXCEEDS_REMAINING,
                )

            # Overwrite the snapshot to what's true AT CONFIRMATION time
            # (§9: these columns are historical record, not stale DRAFT
            # guesses) — see delivery_challan_line.py's docstring.
            dc_line.previously_delivered_quantity = so_line.delivered_quantity
            dc_line.remaining_quantity = live_remaining - dc_line.current_delivery_quantity

            if dc_line.product_id is not None:
                await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=dc_line.product_id)
                product = await inventory.get_active_product_locked(tenant_id, dc_line.product_id)

                await inventory.post_movement(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    product=product,
                    location=location,
                    movement_type=STOCK_OUT,
                    quantity=dc_line.current_delivery_quantity,
                    uom=dc_uom,
                    # Per-line source_id — see module docstring for why.
                    source_type=DELIVERY_CHALLAN,
                    source_id=dc_line.id,
                    audit_action="STOCK_OUT_CREATED",
                    audit_extra={
                        "delivery_challan_id": str(challan.id),
                        "delivery_challan_number": challan.challan_number,
                        "source_sales_order_id": str(order.id),
                    },
                    ip_address=ip_address,
                )

            line_deliveries[so_line.id] = dc_line.current_delivery_quantity

        await so_service.apply_delivery(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            order=order,
            line_deliveries=line_deliveries,
            ip_address=ip_address,
        )

        previous_status = challan.status
        challan.status = CONFIRMED
        challan.updated_by = actor_user_id
        challan.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="DELIVERY_CHALLAN_CONFIRMED",
            entity_type="delivery_challan",
            entity_id=challan.id,
            before={"status": previous_status},
            after={"status": CONFIRMED},
            ip_address=ip_address,
        )

        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == challan.customer_id))
        customer_name = customer_result.scalar_one()
        lines_with_uom = await self._get_lines(challan.id)
        return challan, customer_name, order.order_number, lines_with_uom

    # --- cancel (DRAFT only — see model docstring for why) ------------------

    async def cancel_challan(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        challan_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> DeliveryChallan:
        challan = await self._get_challan_locked(tenant_id, challan_id)
        check_row_version(challan, expected_row_version)

        if challan.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(
                "Only a draft delivery challan can be cancelled — a confirmed challan has already "
                "dispatched stock and cancellation-with-reversal is not yet supported.",
                code=DC_INVALID_STATUS,
            )

        previous_status = challan.status
        challan.status = CANCELLED
        challan.updated_by = actor_user_id
        challan.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="DELIVERY_CHALLAN_CANCELLED",
            entity_type="delivery_challan",
            entity_id=challan.id,
            before={"status": previous_status},
            after={"status": CANCELLED},
            ip_address=ip_address,
        )
        return challan
