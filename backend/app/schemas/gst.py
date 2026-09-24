"""GST Rule Engine & GST Reporting schemas (PROMPT-026)."""

from pydantic import BaseModel


class GstTransactionLineItem(BaseModel):
    line_no: int
    hsn_code: str | None
    quantity: str
    unit_price: str
    gst_rate: str
    taxable_value: str
    cgst_amount: str
    sgst_amount: str
    igst_amount: str
    cess_amount: str
    line_total: str


class GstTransactionListItem(BaseModel):
    id: str
    source_type: str
    source_id: str
    source_number: str | None
    event_type: str
    direction: str
    classification: str
    party_name: str | None
    party_gstin: str | None
    place_of_supply_state_code: str | None
    document_date: str
    financial_year_label: str
    return_period: str
    taxable_value: str
    cgst_amount: str
    sgst_amount: str
    igst_amount: str
    cess_amount: str
    total_gst: str
    total_amount: str


class GstTransactionDetail(GstTransactionListItem):
    lines: list[GstTransactionLineItem]


class ValidationIssueItem(BaseModel):
    code: str
    severity: str
    message: str
    source_type: str
    source_id: str
    field: str
    suggested_action: str


class ValidationResult(BaseModel):
    return_period: str
    is_valid: bool
    error_count: int
    warning_count: int
    issues: list[ValidationIssueItem]
