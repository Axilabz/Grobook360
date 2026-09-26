"""Delivery Challan request/response schemas (PROMPT-014).

No pricing/GST fields anywhere — §9's own header/line field list for this
document type has none (unlike Estimate/Sales Order); a Delivery Challan
is a quantity/dispatch record, not a financial document.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.sales_estimate import UnitRef


class DeliveryLineInput(BaseModel):
    """What a caller submits for one Delivery Challan line — the source
    Sales Order line being (partially) delivered, and how much."""

    sales_order_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateDeliveryChallanRequest(BaseModel):
    sales_order_id: str
    challan_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[DeliveryLineInput] = Field(min_length=1)


class UpdateDeliveryChallanRequest(BaseModel):
    """Only permitted while the challan is DRAFT (§21) — enforced in the
    service layer, not here."""

    challan_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[DeliveryLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class DeliveryChallanActionRequest(BaseModel):
    """Shared body for confirm/cancel — pure status transitions guarded by
    row_version."""

    expected_row_version: int


class DeliveryChallanLineItem(BaseModel):
    id: str
    line_no: int
    source_sales_order_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    ordered_quantity: str
    previously_delivered_quantity: str
    current_delivery_quantity: str
    remaining_quantity: str


class DeliveryChallanListItem(BaseModel):
    id: str
    challan_number: str
    challan_date: str
    source_sales_order_id: str
    source_sales_order_number: str
    customer_id: str
    customer_name: str
    status: str
    total_quantity: str
    created_by: str | None
    created_by_name: str | None = None
    updated_by_name: str | None = None
    created_at: str
    updated_at: str
    row_version: int


class DeliveryChallanDetail(DeliveryChallanListItem):
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    notes: str | None
    lines: list[DeliveryChallanLineItem]


class DeliveryEligibilityLine(BaseModel):
    """One Sales Order line's delivery status — the ordered/delivered/
    remaining breakdown the Create-Delivery-Challan screen needs (§12
    steps 4-7)."""

    sales_order_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    ordered_quantity: str
    delivered_quantity: str
    remaining_quantity: str


class DeliveryEligibility(BaseModel):
    sales_order_id: str
    sales_order_number: str
    sales_order_status: str
    customer_id: str
    customer_name: str
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    lines: list[DeliveryEligibilityLine]
