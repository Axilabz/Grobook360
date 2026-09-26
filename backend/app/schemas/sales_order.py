"""Sales Order request/response schemas (PROMPT-013).

Mirrors `app/schemas/sales_estimate.py`'s shape closely — line input reuses
`SalesLineInput` from PROMPT-011's shared Sales schemas, no second
quantity/discount/GST field set invented for Sales Order specifically.
"""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.sales_common import SalesLineInput
from app.schemas.sales_estimate import UnitRef


class CreateSalesOrderRequest(BaseModel):
    customer_id: str
    order_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] = Field(min_length=1)


class UpdateSalesOrderRequest(BaseModel):
    """Only permitted while the order is DRAFT (§19) — enforced in the
    service layer, not here."""

    customer_id: str | None = None
    order_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class SalesOrderActionRequest(BaseModel):
    """Shared body for confirm/cancel — pure status transitions guarded by
    row_version (§20/§21)."""

    expected_row_version: int


class SalesOrderLineItem(BaseModel):
    id: str
    line_no: int
    product_id: str | None
    description: str | None
    hsn_code: str | None
    quantity: str
    uom: UnitRef
    unit_price: str
    discount_amount: str
    taxable_amount: str
    gst_rate: str
    cgst_amount: str
    sgst_amount: str
    igst_amount: str
    line_total: str


class SalesOrderListItem(BaseModel):
    id: str
    order_number: str
    order_date: str
    customer_id: str
    customer_name: str
    status: str
    source_estimate_id: str | None
    grand_total: str
    created_by: str | None
    created_by_name: str | None = None
    updated_by_name: str | None = None
    created_at: str
    updated_at: str
    row_version: int


class SalesOrderDetail(SalesOrderListItem):
    customer_gstin: str | None
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    tax_total: str
    notes: str | None
    lines: list[SalesOrderLineItem]
