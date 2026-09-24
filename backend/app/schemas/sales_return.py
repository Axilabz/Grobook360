"""Sales Return request/response schemas (PROMPT-016).

Return line input is a distinct, minimal shape (`ReturnLineInput`) —
mirrors `InvoiceFromChallanLineInput`'s exact contract: the caller only
picks WHICH source Sales Invoice line and HOW MUCH of it is being
returned; price/discount/GST are always derived server-side from that
invoice line (see `sales_return_service.py`), never accepted from the
client.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.schemas.sales_estimate import UnitRef


class ReturnLineInput(BaseModel):
    """What a caller submits for one Sales Return line — the source Sales
    Invoice line being (partially) returned, and how much."""

    source_invoice_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateSalesReturnRequest(BaseModel):
    source_invoice_id: str
    return_date: date | None = None
    return_reason: str
    reason_description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReturnLineInput] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_reason_description(self) -> "CreateSalesReturnRequest":
        # §8: a description is required when the reason is OTHER (the
        # only reason with no self-explanatory meaning) — enforced here
        # for immediate client feedback; the service layer re-validates
        # authoritatively.
        if self.return_reason == "OTHER" and not (self.reason_description and self.reason_description.strip()):
            raise ValueError("reason_description is required when return_reason is OTHER")
        return self


class UpdateSalesReturnRequest(BaseModel):
    """Only permitted while the return is DRAFT (§24) — enforced in the
    service layer, not here."""

    return_date: date | None = None
    return_reason: str | None = None
    reason_description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[ReturnLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class SalesReturnActionRequest(BaseModel):
    """Shared body for confirm/cancel — pure status transitions guarded by
    row_version."""

    expected_row_version: int


class SalesReturnLineItem(BaseModel):
    id: str
    line_no: int
    source_invoice_line_id: str
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


class SalesReturnListItem(BaseModel):
    id: str
    return_number: str
    return_date: str
    customer_id: str
    customer_name: str
    source_invoice_id: str
    source_invoice_number: str
    status: str
    return_reason: str
    total_return_quantity: str
    grand_total: str
    tax_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class SalesReturnDetail(SalesReturnListItem):
    customer_gstin: str | None
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    reason_description: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    notes: str | None
    accounting_posting_reference: str | None
    gst_transaction_reference: str | None
    lines: list[SalesReturnLineItem]


class ReturnEligibilityLine(BaseModel):
    """One Sales Invoice line's returnable status — the invoiced/
    previously-returned/returnable breakdown the Create-Return screen
    needs (§7/§14 steps 5-7)."""

    source_invoice_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    original_quantity: str
    previously_returned_quantity: str
    returnable_quantity: str
    unit_price: str
    gst_rate: str


class ReturnEligibility(BaseModel):
    source_invoice_id: str
    source_invoice_number: str
    source_invoice_status: str
    customer_id: str
    customer_name: str
    customer_gstin: str | None
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    lines: list[ReturnEligibilityLine]
