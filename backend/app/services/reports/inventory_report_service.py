"""Inventory reports (PROMPT-027 §22-§25).

Every report here derives from `stock_ledger_entry` — the sole
inventory source of truth (unchanged since PROMPT-010) — never from
Sales/Purchase reports (§25 "do not reconstruct stock history from
sales reports"). `stock_ledger_entry` has no running-balance column of
its own (confirmed by code reading); "current stock" is `product.
stock_qty_cache` (the ledger's own maintained cache, PROMPT-010 §—
"never write to it from anywhere else"), and a historical/point-in-time
balance is `SUM(quantity * MOVEMENT_DIRECTION[movement_type])` over the
ledger up to that point.

Date basis: `occurred_at` (the movement's own timestamp).

§23's LOW_STOCK status is only ever computed by comparing `stock_qty_
cache` against `reorder_level` — `reorder_level` is confirmed to have NO
write path anywhere in this codebase (stays at its default 0), so this
report's own LOW_STOCK bucket is inert until a future prompt gives
`reorder_level` a real writer (documented limitation, not a bug).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.stock_ledger_entry import MOVEMENT_DIRECTION, StockLedgerEntry
from app.models.unit_of_measure import UnitOfMeasure

_ZERO = Decimal("0")

IN_STOCK = "IN_STOCK"
LOW_STOCK = "LOW_STOCK"
OUT_OF_STOCK = "OUT_OF_STOCK"


def _stock_status(quantity: Decimal, reorder_level: Decimal) -> str:
    if quantity <= _ZERO:
        return OUT_OF_STOCK
    if reorder_level > _ZERO and quantity <= reorder_level:
        return LOW_STOCK
    return IN_STOCK


class InventoryReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Current Stock (§23) -------------------------------------------------

    async def get_current_stock(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, status_filter: str | None, search: str | None,
    ) -> tuple[list[dict], int]:
        conditions = [Product.tenant_id == tenant_id]
        if search:
            like = f"%{search}%"
            conditions.append((Product.name.ilike(like)) | (Product.sku.ilike(like)))

        base = (
            select(Product.id, Product.sku, Product.name, Product.stock_qty_cache, Product.reorder_level, UnitOfMeasure.code)
            .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_uom_id)
            .where(*conditions)
        )
        rows = (await self._session.execute(base)).all()

        items = []
        for product_id, sku, name, qty, reorder_level, uom_code in rows:
            status = _stock_status(qty, reorder_level)
            if status_filter and status != status_filter:
                continue
            items.append({"product_id": str(product_id), "sku": sku, "product_name": name, "uom": uom_code, "current_quantity": qty, "reorder_level": reorder_level, "stock_status": status})

        items.sort(key=lambda i: i["product_name"])
        total_items = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total_items

    # --- Stock Movement Report (§24/§25) --------------------------------------

    async def list_stock_movements(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None,
        product_id: uuid.UUID | None, movement_type: str | None,
    ) -> tuple[list[dict], int]:
        conditions = [StockLedgerEntry.tenant_id == tenant_id]
        if date_from is not None:
            conditions.append(StockLedgerEntry.occurred_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to is not None:
            conditions.append(StockLedgerEntry.occurred_at <= datetime.combine(date_to, datetime.max.time()))
        if product_id is not None:
            conditions.append(StockLedgerEntry.product_id == product_id)
        if movement_type:
            conditions.append(StockLedgerEntry.movement_type == movement_type)

        base = (
            select(StockLedgerEntry, Product.sku, Product.name)
            .join(Product, Product.id == StockLedgerEntry.product_id)
            .where(*conditions)
        )
        count_stmt = select(func.count()).select_from(select(StockLedgerEntry.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(StockLedgerEntry.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        items = []
        for entry, sku, name in rows:
            direction = MOVEMENT_DIRECTION[entry.movement_type]
            items.append({
                "date": entry.occurred_at.isoformat(), "product_sku": sku, "product_name": name, "movement_type": entry.movement_type,
                "quantity_in": entry.quantity if direction > 0 else _ZERO, "quantity_out": entry.quantity if direction < 0 else _ZERO,
                "source_type": entry.source_type, "source_id": str(entry.source_id), "created_by": str(entry.created_by) if entry.created_by else None,
            })
        return items, total_items

    # --- Product Stock History (§22 item 6) — running balance for one product

    async def get_product_stock_history(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID, date_from: date | None, date_to: date | None,
    ) -> tuple[Decimal, list[dict]]:
        opening_balance = _ZERO
        if date_from is not None:
            opening_stmt = select(StockLedgerEntry.movement_type, StockLedgerEntry.quantity).where(
                StockLedgerEntry.tenant_id == tenant_id, StockLedgerEntry.product_id == product_id,
                StockLedgerEntry.occurred_at < datetime.combine(date_from, datetime.min.time()),
            )
            for movement_type, quantity in (await self._session.execute(opening_stmt)).all():
                opening_balance += quantity * MOVEMENT_DIRECTION[movement_type]

        conditions = [StockLedgerEntry.tenant_id == tenant_id, StockLedgerEntry.product_id == product_id]
        if date_from is not None:
            conditions.append(StockLedgerEntry.occurred_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to is not None:
            conditions.append(StockLedgerEntry.occurred_at <= datetime.combine(date_to, datetime.max.time()))

        rows = (await self._session.execute(select(StockLedgerEntry).where(*conditions).order_by(StockLedgerEntry.occurred_at))).scalars().all()

        running = opening_balance
        history = []
        for entry in rows:
            running += entry.quantity * MOVEMENT_DIRECTION[entry.movement_type]
            history.append({
                "date": entry.occurred_at.isoformat(), "movement_type": entry.movement_type, "quantity": entry.quantity,
                "balance": running, "source_type": entry.source_type, "source_id": str(entry.source_id),
            })
        return opening_balance, history
