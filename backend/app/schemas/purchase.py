"""Purchase Management Foundation request/response schemas (PROMPT-019).

Covers all four document types (Purchase Order, Goods Receipt, Purchase
Invoice, Purchase Return) in one file, mirroring the combined shape of
`sales_estimate.py`/`sales_invoice.py`/`sales_return.py` put together —
appropriate for a foundation prompt that establishes the common
architecture rather than four fully independent modules.

Line inputs for Goods Receipt/Purchase-Invoice-from-GR/Purchase Return
all follow the same minimal "which source line, how much" shape already
established by `InvoiceFromChallanLineInput`/`ReturnLineInput` — price/
GST are always derived server-side from the source line, never accepted
from the client.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.schemas.sales_estimate import UnitRef

# --- Purchase Order ---


class PurchaseOrderLineInput(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    unit_price: Decimal = Field(ge=0, decimal_places=2)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    discount_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)

    @model_validator(mode="after")
    def _validate_discount(self) -> "PurchaseOrderLineInput":
        if self.discount_percent is not None and self.discount_amount is not None:
            raise ValueError("Specify either discount_percent or discount_amount, not both")
        return self


class CreatePurchaseOrderRequest(BaseModel):
    supplier_id: str
    document_date: date | None = None
    supplier_reference: str | None = Field(default=None, max_length=100)
    expected_delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=200)
    delivery_terms: str | None = Field(default=None, max_length=200)
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[PurchaseOrderLineInput] = Field(min_length=1)


class UpdatePurchaseOrderRequest(BaseModel):
    document_date: date | None = None
    supplier_reference: str | None = Field(default=None, max_length=100)
    expected_delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=200)
    delivery_terms: str | None = Field(default=None, max_length=200)
    shipping_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[PurchaseOrderLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class PurchaseOrderActionRequest(BaseModel):
    expected_row_version: int


class PurchaseOrderLineItem(BaseModel):
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
    received_quantity: str
    remaining_quantity: str


class PurchaseOrderListItem(BaseModel):
    id: str
    po_number: str
    document_date: str
    supplier_id: str
    supplier_name: str
    supplier_reference: str | None
    expected_delivery_date: str | None
    status: str
    total_ordered_quantity: str
    total_received_quantity: str
    total_remaining_quantity: str
    grand_total: str
    tax_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class PurchaseOrderDetail(PurchaseOrderListItem):
    supplier_gstin: str | None
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    payment_terms: str | None
    delivery_terms: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    notes: str | None
    lines: list[PurchaseOrderLineItem]


# --- Purchase Order supporting endpoints (PROMPT-020) ---


class PurchaseOrderRelatedGoodsReceipt(BaseModel):
    id: str
    grn_number: str
    document_date: str
    status: str
    total_quantity: str
    created_at: str


class PurchaseOrderRelatedInvoice(BaseModel):
    id: str
    purchase_invoice_number: str
    document_date: str
    status: str
    grand_total: str
    source_goods_receipt_id: str | None


class PurchaseOrderRelatedDocuments(BaseModel):
    purchase_order_id: str
    goods_receipts: list[PurchaseOrderRelatedGoodsReceipt]
    purchase_invoices: list[PurchaseOrderRelatedInvoice]


class PurchaseOrderReceivingSummaryLine(BaseModel):
    purchase_order_line_id: str
    product_id: str | None
    description: str | None
    uom: UnitRef
    ordered_quantity: str
    received_quantity: str
    remaining_quantity: str


class PurchaseOrderReceivingSummary(BaseModel):
    purchase_order_id: str
    po_number: str
    status: str
    total_ordered_quantity: str
    total_received_quantity: str
    total_remaining_quantity: str
    lines: list[PurchaseOrderReceivingSummaryLine]


class PurchaseOrderAuditEvent(BaseModel):
    id: str
    action: str
    actor_user_id: str | None
    occurred_at: str
    before: dict | None
    after: dict | None


class PurchaseOrderAuditHistory(BaseModel):
    purchase_order_id: str
    events: list[PurchaseOrderAuditEvent]


# --- Goods Receipt ---


class ReceiptLineInput(BaseModel):
    purchase_order_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateGoodsReceiptRequest(BaseModel):
    purchase_order_id: str
    document_date: date | None = None
    supplier_delivery_note: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReceiptLineInput] = Field(min_length=1)


class UpdateGoodsReceiptRequest(BaseModel):
    document_date: date | None = None
    supplier_delivery_note: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReceiptLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class GoodsReceiptActionRequest(BaseModel):
    expected_row_version: int


class GoodsReceiptLineItem(BaseModel):
    id: str
    line_no: int
    source_purchase_order_line_id: str | None
    product_id: str | None
    description: str | None
    hsn_code: str | None
    ordered_quantity: str
    previously_received_quantity: str
    quantity: str
    remaining_quantity: str
    uom: UnitRef
    unit_price: str
    taxable_amount: str
    gst_rate: str
    line_total: str
    invoiced_quantity: str
    # §42 Stock Impact Visibility: the stock_ledger_entry this line's
    # STOCK_IN posted as, once the GR is CONFIRMED (null while DRAFT, and
    # null again once reversed — see `stock_movement_reversed`).
    stock_movement_id: str | None = None
    stock_movement_reversed: bool = False


class GoodsReceiptListItem(BaseModel):
    id: str
    grn_number: str
    document_date: str
    supplier_id: str
    supplier_name: str
    supplier_delivery_note: str | None
    source_purchase_order_id: str | None
    source_purchase_order_number: str | None
    status: str
    total_quantity: str
    grand_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class GoodsReceiptDetail(GoodsReceiptListItem):
    notes: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    tax_total: str
    lines: list[GoodsReceiptLineItem]


# --- Goods Receipt supporting endpoints (PROMPT-021) ---


class GoodsReceiptRelatedInvoice(BaseModel):
    id: str
    purchase_invoice_number: str
    document_date: str
    status: str
    grand_total: str


class GoodsReceiptRelatedDocuments(BaseModel):
    goods_receipt_id: str
    source_purchase_order_id: str | None
    source_purchase_order_number: str | None
    source_purchase_order_status: str | None
    purchase_invoices: list[GoodsReceiptRelatedInvoice]


class GoodsReceiptAuditEvent(BaseModel):
    id: str
    action: str
    actor_user_id: str | None
    occurred_at: str
    before: dict | None
    after: dict | None


class GoodsReceiptAuditHistory(BaseModel):
    goods_receipt_id: str
    events: list[GoodsReceiptAuditEvent]


class ReceiptEligibilityLine(BaseModel):
    purchase_order_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    unit_price: str
    gst_rate: str
    ordered_quantity: str
    received_quantity: str
    remaining_quantity: str


class ReceiptEligibility(BaseModel):
    purchase_order_id: str
    purchase_order_number: str
    purchase_order_status: str
    supplier_id: str
    supplier_name: str
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    lines: list[ReceiptEligibilityLine]


# --- Purchase Invoice ---


class DirectPurchaseInvoiceLineInput(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    unit_price: Decimal = Field(ge=0, decimal_places=2)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    discount_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)

    @model_validator(mode="after")
    def _validate_discount(self) -> "DirectPurchaseInvoiceLineInput":
        if self.discount_percent is not None and self.discount_amount is not None:
            raise ValueError("Specify either discount_percent or discount_amount, not both")
        return self


class CreateDirectPurchaseInvoiceRequest(BaseModel):
    supplier_id: str
    document_date: date | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    supplier_invoice_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[DirectPurchaseInvoiceLineInput] = Field(min_length=1)


class InvoiceFromReceiptLineInput(BaseModel):
    source_goods_receipt_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateInvoiceFromReceiptRequest(BaseModel):
    document_date: date | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    supplier_invoice_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[InvoiceFromReceiptLineInput] = Field(min_length=1)


class InvoiceFromPurchaseOrderLineInput(BaseModel):
    purchase_order_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateInvoiceFromPurchaseOrderRequest(BaseModel):
    document_date: date | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    supplier_invoice_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[InvoiceFromPurchaseOrderLineInput] = Field(min_length=1)


class UpdatePurchaseInvoiceRequest(BaseModel):
    document_date: date | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    supplier_invoice_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[DirectPurchaseInvoiceLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class PurchaseInvoiceActionRequest(BaseModel):
    expected_row_version: int


class PurchaseInvoiceLineItem(BaseModel):
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
    source_goods_receipt_line_id: str | None
    source_purchase_order_line_id: str | None
    returned_quantity: str
    # §42/§46-style Stock Impact Visibility, mirrors Goods Receipt's own
    # (PROMPT-021) — populated only for a DIRECT invoice's lines.
    stock_movement_id: str | None = None
    stock_movement_reversed: bool = False


class PurchaseInvoiceListItem(BaseModel):
    id: str
    purchase_invoice_number: str
    supplier_invoice_number: str | None
    document_date: str
    supplier_invoice_date: str | None
    due_date: str | None
    invoice_type: str
    supplier_id: str
    supplier_name: str
    status: str
    source_goods_receipt_id: str | None
    source_goods_receipt_number: str | None
    source_purchase_order_id: str | None
    source_purchase_order_number: str | None
    # §12/§46: the system-determined decision, never user-editable.
    stock_impact: str
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


class PurchaseInvoiceDetail(PurchaseInvoiceListItem):
    supplier_gstin: str | None
    place_of_supply_state_code: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    notes: str | None
    # §7: non-blocking duplicate-supplier-invoice-number detection —
    # never rejects the request, just flags it (uniqueness policy is an
    # explicit Open Decision, not silently enforced).
    duplicate_supplier_invoice_warning: bool
    # PROMPT-025: opaque accounting-journal reference, mirrors
    # sales_invoice's own column/field.
    accounting_posting_reference: str | None
    # PROMPT-026: gst_transaction id reference, mirrors sales_invoice's
    # own column/field.
    gst_transaction_reference: str | None
    lines: list[PurchaseInvoiceLineItem]


class InvoiceEligibilityLine(BaseModel):
    source_goods_receipt_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    received_quantity: str
    invoiced_quantity: str
    invoiceable_quantity: str
    unit_price: str
    gst_rate: str


class InvoiceEligibility(BaseModel):
    source_goods_receipt_id: str
    source_goods_receipt_number: str
    source_goods_receipt_status: str
    supplier_id: str
    supplier_name: str
    lines: list[InvoiceEligibilityLine]


# --- PO-level invoiceable items (PROMPT-022 "Supported Flow 2") ---


class PurchaseOrderInvoiceEligibilityLine(BaseModel):
    purchase_order_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    unit_price: str
    gst_rate: str
    ordered_quantity: str
    received_quantity: str
    invoiced_quantity: str
    invoiceable_quantity: str


class PurchaseOrderInvoiceEligibility(BaseModel):
    purchase_order_id: str
    purchase_order_number: str
    purchase_order_status: str
    supplier_id: str
    supplier_name: str
    lines: list[PurchaseOrderInvoiceEligibilityLine]


# --- Purchase Invoice supporting endpoints (PROMPT-022) ---


class PurchaseInvoiceRelatedGoodsReceipt(BaseModel):
    id: str
    grn_number: str
    document_date: str
    status: str


class PurchaseInvoiceRelatedReturn(BaseModel):
    id: str
    purchase_return_number: str
    document_date: str
    status: str
    grand_total: str


class PurchaseInvoiceRelatedDocuments(BaseModel):
    purchase_invoice_id: str
    source_purchase_order_id: str | None
    source_purchase_order_number: str | None
    source_purchase_order_status: str | None
    goods_receipts: list[PurchaseInvoiceRelatedGoodsReceipt]
    purchase_returns: list[PurchaseInvoiceRelatedReturn]


class PurchaseInvoiceAuditEvent(BaseModel):
    id: str
    action: str
    actor_user_id: str | None
    occurred_at: str
    before: dict | None
    after: dict | None


class PurchaseInvoiceAuditHistory(BaseModel):
    purchase_invoice_id: str
    events: list[PurchaseInvoiceAuditEvent]


# --- Purchase Return ---


class ReturnLineInput(BaseModel):
    source_purchase_invoice_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreatePurchaseReturnRequest(BaseModel):
    source_purchase_invoice_id: str
    document_date: date | None = None
    return_reason: str
    reason_description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReturnLineInput] = Field(min_length=1)


class UpdatePurchaseReturnRequest(BaseModel):
    document_date: date | None = None
    return_reason: str | None = None
    reason_description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReturnLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class PurchaseReturnActionRequest(BaseModel):
    expected_row_version: int


class PurchaseReturnLineItem(BaseModel):
    id: str
    line_no: int
    source_purchase_invoice_line_id: str
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
    # §18/§42 Stock Impact Visibility: the stock_ledger_entry this line's
    # STOCK_OUT posted as, once the Return is CONFIRMED (null while
    # DRAFT, and stock_movement_reversed=true once a cancellation
    # reversal has been posted against it).
    stock_movement_id: str | None = None
    stock_movement_reversed: bool = False


class PurchaseReturnListItem(BaseModel):
    id: str
    purchase_return_number: str
    document_date: str
    supplier_id: str
    supplier_name: str
    source_purchase_invoice_id: str
    source_purchase_invoice_number: str
    status: str
    return_reason: str
    total_return_quantity: str
    grand_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class PurchaseReturnDetail(PurchaseReturnListItem):
    reason_description: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    tax_total: str
    notes: str | None
    # PROMPT-025: opaque accounting-journal reference, mirrors
    # sales_return's own column/field.
    accounting_posting_reference: str | None
    # PROMPT-026: gst_transaction id reference, mirrors sales_return's
    # own column/field.
    gst_transaction_reference: str | None
    lines: list[PurchaseReturnLineItem]


class PurchaseReturnEligibilityLine(BaseModel):
    source_purchase_invoice_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    original_quantity: str
    previously_returned_quantity: str
    returnable_quantity: str
    unit_price: str
    gst_rate: str


class PurchaseReturnEligibility(BaseModel):
    source_purchase_invoice_id: str
    source_purchase_invoice_number: str
    source_purchase_invoice_status: str
    supplier_id: str
    supplier_name: str
    lines: list[PurchaseReturnEligibilityLine]


# --- Purchase Return supporting endpoints (PROMPT-023) ---


class PurchaseReturnRelatedGoodsReceipt(BaseModel):
    id: str
    grn_number: str
    document_date: str
    status: str


class PurchaseReturnRelatedDocuments(BaseModel):
    purchase_return_id: str
    source_purchase_invoice_id: str
    source_purchase_invoice_number: str
    source_purchase_invoice_status: str
    source_purchase_order_id: str | None
    source_purchase_order_number: str | None
    goods_receipts: list[PurchaseReturnRelatedGoodsReceipt]


class PurchaseReturnAuditEvent(BaseModel):
    id: str
    action: str
    actor_user_id: str | None
    occurred_at: str
    before: dict | None
    after: dict | None


class PurchaseReturnAuditHistory(BaseModel):
    purchase_return_id: str
    events: list[PurchaseReturnAuditEvent]
