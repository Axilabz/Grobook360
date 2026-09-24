"""Sales Invoice request/response schemas (PROMPT-015).

Direct-invoice line input reuses `SalesLineInput` from PROMPT-011's
shared Sales schemas (quantity/unit_price/discount, fully server-
recalculated). Invoice-from-Delivery-Challan line input is a distinct,
smaller shape (`InvoiceFromChallanLineInput`) — the caller only picks
WHICH delivered line and HOW MUCH of it to bill now; price/GST are always
derived server-side from the source Sales Order line (see
`sales_invoice_service.py`), never accepted from the client.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.sales_common import SalesLineInput
from app.schemas.sales_estimate import UnitRef


class CreateDirectInvoiceRequest(BaseModel):
    customer_id: str
    invoice_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] = Field(min_length=1)


class InvoiceFromChallanLineInput(BaseModel):
    """What a caller submits for one Delivery-Challan-sourced invoice
    line — the source Delivery Challan line being (partially) billed, and
    how much."""

    source_delivery_challan_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateInvoiceFromChallanRequest(BaseModel):
    invoice_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[InvoiceFromChallanLineInput] = Field(min_length=1)


class UpdateSalesInvoiceRequest(BaseModel):
    """Only permitted while the invoice is DRAFT (§34) — enforced in the
    service layer, not here. Only header fields not tied to the
    source-quantity reconciliation are editable; line quantities for a
    DC-based invoice are NOT re-editable via this endpoint (cancel and
    recreate instead) to avoid re-deriving the same invoiceable-quantity
    validation twice in two different code paths."""

    invoice_date: date | None = None
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class SalesInvoiceActionRequest(BaseModel):
    """Shared body for post/cancel — pure status transitions guarded by
    row_version."""

    expected_row_version: int


class SalesInvoiceLineItem(BaseModel):
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
    source_delivery_challan_line_id: str | None


class SalesInvoiceListItem(BaseModel):
    id: str
    invoice_number: str
    invoice_date: str
    invoice_type: str
    customer_id: str
    customer_name: str
    status: str
    source_delivery_challan_id: str | None
    source_delivery_challan_number: str | None
    grand_total: str
    tax_total: str
    # PROMPT-024 §15/§16: reconciliation CACHE fields — read-only,
    # never an API input, only ever written by PaymentService.
    paid_amount: str
    payment_status: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class SalesInvoiceDetail(SalesInvoiceListItem):
    customer_gstin: str | None
    customer_type: str
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    source_sales_order_id: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    notes: str | None
    accounting_posting_reference: str | None
    gst_transaction_reference: str | None
    irn: str | None
    ack_number: str | None
    ack_date: str | None
    einvoice_status: str | None
    lines: list[SalesInvoiceLineItem]


class InvoiceEligibilityLine(BaseModel):
    """One Delivery Challan line's invoiceable status — the delivered/
    invoiced/invoiceable breakdown the Create-Invoice-from-DC screen
    needs (§13 steps 3-4)."""

    source_delivery_challan_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    delivered_quantity: str
    invoiced_quantity: str
    invoiceable_quantity: str
    unit_price: str
    gst_rate: str


class InvoiceEligibility(BaseModel):
    source_delivery_challan_id: str
    source_delivery_challan_number: str
    source_delivery_challan_status: str
    customer_id: str
    customer_name: str
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    lines: list[InvoiceEligibilityLine]
