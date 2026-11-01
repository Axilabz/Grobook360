"""Inventory / Stock Ledger request/response schemas (PROMPT-010).

Quantities are always Decimal (NUMERIC-backed) — never float — per §10/§28.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class UnitRef(BaseModel):
    id: str
    code: str
    name: str


class InventoryListItem(BaseModel):
    product_id: str
    sku: str
    name: str
    base_uom: UnitRef
    current_stock: str
    reorder_level: str
    is_low_stock: bool
    product_status: str
    last_movement_at: str | None


class StockMovementItem(BaseModel):
    id: str
    movement_type: str
    quantity: str
    uom: UnitRef
    base_quantity: str
    source_type: str
    source_id: str
    occurred_at: str
    created_by: str | None
    unit_cost: str | None = None


class AvailabilityResponse(BaseModel):
    product_id: str
    available_quantity: str
    base_uom: UnitRef


# `unit_cost` (all optional, Weighted Average Cost — per the product's
# BASE unit, same denomination as Product.cost_price) feeds the Manual
# Stock Movements -> Accounting integration. Omitting it still records the
# stock movement fine; it just posts no accounting journal for that
# movement (see InventoryService's own docstrings).

class OpeningStockRequest(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    unit_cost: Decimal | None = Field(default=None, gt=0, decimal_places=2)


class StockInRequest(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    notes: str | None = Field(default=None, max_length=500)
    unit_cost: Decimal | None = Field(default=None, gt=0, decimal_places=2)


class StockOutRequest(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    notes: str | None = Field(default=None, max_length=500)


class AdjustmentRequest(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    direction: Literal["IN", "OUT"]
    reason: str = Field(min_length=1, max_length=500)
    unit_cost: Decimal | None = Field(default=None, gt=0, decimal_places=2)
