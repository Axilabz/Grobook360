"""Credit Note / Debit Note request/response schemas (PROMPT-017).

Note line input is a distinct, minimal shape (`AdjustmentLineInput`) —
mirrors `ReturnLineInput`'s exact contract: the caller only picks WHICH
source Sales Invoice line and HOW MUCH of it is being adjusted;
price/discount/GST are always derived server-side from that invoice line
(see `credit_debit_note_service.py`), never accepted from the client.

`reason` is free text (§4/§53 open decision #20 — no controlled taxonomy
is invented here, unlike Sales Return's own prompt).
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.sales_estimate import UnitRef

NOTE_TYPE_VALUES = {"CREDIT_NOTE", "DEBIT_NOTE"}


class AdjustmentLineInput(BaseModel):
    """What a caller submits for one Credit/Debit Note line — the source
    Sales Invoice line being (partially) adjusted, and how much."""

    source_invoice_line_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)


class CreateCreditDebitNoteRequest(BaseModel):
    source_invoice_id: str
    note_type: str
    note_date: date | None = None
    reason: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[AdjustmentLineInput] = Field(min_length=1)

    @field_validator("note_type")
    @classmethod
    def _validate_note_type(cls, value: str) -> str:
        if value not in NOTE_TYPE_VALUES:
            raise ValueError(f"note_type must be one of {sorted(NOTE_TYPE_VALUES)}")
        return value


class UpdateCreditDebitNoteRequest(BaseModel):
    """Only permitted while the note is DRAFT (§29) — enforced in the
    service layer, not here."""

    note_date: date | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[AdjustmentLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int


class CreditDebitNoteActionRequest(BaseModel):
    """Shared body for post/cancel — pure status transitions guarded by
    row_version."""

    expected_row_version: int


class CreditDebitNoteLineItem(BaseModel):
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


class CreditDebitNoteListItem(BaseModel):
    id: str
    note_number: str
    note_type: str
    note_date: str
    customer_id: str
    customer_name: str
    source_invoice_id: str
    source_invoice_number: str
    status: str
    reason: str
    grand_total: str
    tax_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class CreditDebitNoteDetail(CreditDebitNoteListItem):
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
    notes: str | None
    accounting_posting_reference: str | None
    gst_transaction_reference: str | None
    lines: list[CreditDebitNoteLineItem]


class AdjustmentEligibilityLine(BaseModel):
    """One Sales Invoice line's adjustable status — the invoiced/
    previously-credited/previously-debited/eligible breakdown the
    Create-Note screen needs (§17/§24)."""

    source_invoice_line_id: str
    product_id: str | None
    description: str | None
    hsn_code: str | None
    uom: UnitRef
    original_quantity: str
    previously_credited_quantity: str
    previously_debited_quantity: str
    creditable_quantity: str
    debitable_quantity: str
    unit_price: str
    gst_rate: str


class AdjustmentEligibility(BaseModel):
    source_invoice_id: str
    source_invoice_number: str
    source_invoice_status: str
    customer_id: str
    customer_name: str
    customer_gstin: str | None
    billing_address: str | None
    shipping_address: str | None
    place_of_supply_state_code: str | None
    lines: list[AdjustmentEligibilityLine]
