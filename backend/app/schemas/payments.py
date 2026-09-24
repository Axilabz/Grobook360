"""Payments & Collections request/response schemas (PROMPT-024).

One shared schema surface for both directions (Customer Receipt /
Supplier Payment) — mirrors `PaymentService`'s own "one service, two
thin routers" architecture. `party_type`/`customer_id`/`supplier_id`
are never accepted directly from either router's create payload — each
router (`customer_receipts.py`/`supplier_payments.py`) supplies its own
fixed `party_type` and the one party-id field relevant to it, so a
caller cannot even construct a wrong-party request through the wrong
URL (§4).

Allocation line input mirrors `ReturnLineInput`/`AdjustmentLineInput`'s
minimal shape: the caller only picks WHICH invoice and HOW MUCH — the
backend always re-validates against live outstanding, never trusting a
client-submitted total (§27).
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class AllocationLineInput(BaseModel):
    invoice_id: str
    allocated_amount: Decimal = Field(gt=0, decimal_places=2)


class CreateCustomerReceiptRequest(BaseModel):
    customer_id: str
    payment_date: date | None = None
    payment_method: str
    amount: Decimal = Field(gt=0, decimal_places=2)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    client_transaction_id: str | None = Field(default=None, max_length=100)
    cheque_number: str | None = Field(default=None, max_length=50)
    cheque_date: date | None = None
    cheque_bank_name: str | None = Field(default=None, max_length=200)
    allocations: list[AllocationLineInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_cheque_fields(self) -> "CreateCustomerReceiptRequest":
        if self.payment_method == "CHEQUE" and (not self.cheque_number or not self.cheque_date):
            raise ValueError("cheque_number and cheque_date are required when payment_method is CHEQUE")
        return self


class CreateSupplierPaymentRequest(BaseModel):
    supplier_id: str
    payment_date: date | None = None
    payment_method: str
    amount: Decimal = Field(gt=0, decimal_places=2)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    client_transaction_id: str | None = Field(default=None, max_length=100)
    cheque_number: str | None = Field(default=None, max_length=50)
    cheque_date: date | None = None
    cheque_bank_name: str | None = Field(default=None, max_length=200)
    allocations: list[AllocationLineInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_cheque_fields(self) -> "CreateSupplierPaymentRequest":
        if self.payment_method == "CHEQUE" and (not self.cheque_number or not self.cheque_date):
            raise ValueError("cheque_number and cheque_date are required when payment_method is CHEQUE")
        return self


class UpdatePaymentRequest(BaseModel):
    """Only permitted while the payment is DRAFT — enforced in the
    service layer, not here."""

    payment_date: date | None = None
    payment_method: str | None = None
    amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    cheque_number: str | None = Field(default=None, max_length=50)
    cheque_date: date | None = None
    cheque_bank_name: str | None = Field(default=None, max_length=200)
    allocations: list[AllocationLineInput] | None = None
    expected_row_version: int


class PaymentActionRequest(BaseModel):
    expected_row_version: int


class ChequeStatusRequest(BaseModel):
    expected_row_version: int
    cheque_status: str
    cleared_date: date | None = None


class PaymentAllocationItem(BaseModel):
    id: str
    invoice_id: str
    invoice_type: str  # 'SALES_INVOICE' | 'PURCHASE_INVOICE'
    invoice_number: str
    allocated_amount: str


class PaymentListItem(BaseModel):
    id: str
    payment_number: str
    party_type: str
    customer_id: str | None
    supplier_id: str | None
    party_name: str
    payment_date: str
    payment_method: str
    amount: str
    allocated_amount: str
    unallocated_amount: str
    status: str
    cheque_status: str | None
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class PaymentDetail(PaymentListItem):
    reference_number: str | None
    notes: str | None
    client_transaction_id: str | None
    cheque_number: str | None
    cheque_date: str | None
    cheque_bank_name: str | None
    cleared_date: str | None
    accounting_posting_reference: str | None
    allocations: list[PaymentAllocationItem]


class OutstandingInvoiceItem(BaseModel):
    invoice_id: str
    invoice_number: str
    invoice_date: str
    invoice_total: str
    paid_amount: str
    outstanding_amount: str
    payment_status: str


class OutstandingInvoicesResponse(BaseModel):
    party_type: str
    party_id: str
    party_name: str
    invoices: list[OutstandingInvoiceItem]
