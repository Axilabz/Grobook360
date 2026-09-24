"""Sales Estimate request/response schemas (PROMPT-012).

Line input reuses `SalesLineInput` from PROMPT-011's shared Sales schemas
— no second quantity/discount/GST field set invented for Estimate
specifically.
"""

from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.schemas.sales_common import SalesLineInput


class UnitRef(BaseModel):
    id: str
    code: str
    name: str


class CreateEstimateRequest(BaseModel):
    customer_id: str
    document_date: date | None = None
    valid_until_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_dates(self) -> "CreateEstimateRequest":
        if self.document_date and self.valid_until_date and self.valid_until_date < self.document_date:
            raise ValueError("Valid-until date cannot be before the estimate date")
        return self


class UpdateEstimateRequest(BaseModel):
    """Only permitted while the estimate is DRAFT (§16) — enforced in the
    service layer, not here."""

    customer_id: str | None = None
    document_date: date | None = None
    valid_until_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[SalesLineInput] | None = Field(default=None, min_length=1)
    expected_row_version: int

    @model_validator(mode="after")
    def _validate_dates(self) -> "UpdateEstimateRequest":
        if self.document_date and self.valid_until_date and self.valid_until_date < self.document_date:
            raise ValueError("Valid-until date cannot be before the estimate date")
        return self


class EstimateActionRequest(BaseModel):
    """Shared body for send/accept/reject/cancel/convert — all are pure
    status transitions guarded by row_version (§23/§63)."""

    expected_row_version: int


class EstimateLineItem(BaseModel):
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


class EstimateListItem(BaseModel):
    id: str
    estimate_number: str
    document_date: str
    valid_until_date: str | None
    customer_id: str
    customer_name: str
    status: str
    is_expired_display: bool
    grand_total: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class EstimateDetail(EstimateListItem):
    customer_gstin: str | None
    billing_address: str | None
    place_of_supply_state_code: str | None
    subtotal: str
    discount_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str
    igst_total: str
    tax_total: str
    notes: str | None
    converted_at: str | None
    lines: list[EstimateLineItem]


class ConversionResult(BaseModel):
    """§21 PROMPT-012 established this boundary; PROMPT-013 fills it in —
    `sales_order_id` now identifies a real, persisted Sales Order."""

    estimate_id: str
    status: str
    converted_at: str | None
    sales_order_id: str | None = None
    message: str
