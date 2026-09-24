"""Shared Sales & Billing schemas (PROMPT-011).

These are the reusable line-level input/output shapes every future
document-type prompt (Estimate, Sales Order, Delivery Challan, Sales
Invoice, Sales Return) should compose rather than each inventing its own
quantity/discount/GST field set — the actual document header/line DB
tables belong to those future prompts, not this one.
"""

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class SalesLineInput(BaseModel):
    """What a caller submits for one Sales line — before server-side
    calculation. Mirrors the approved quantity/price precision from
    PROMPT-009/010 (NUMERIC, never float)."""

    product_id: str
    quantity: Decimal = Field(gt=0, decimal_places=3)
    uom_id: str
    unit_price: Decimal = Field(ge=0, decimal_places=2)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    discount_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)

    @model_validator(mode="after")
    def _validate_discount(self) -> "SalesLineInput":
        # §12: discount is percentage OR fixed amount — not both at once,
        # since combining them has no approved, unambiguous meaning.
        if self.discount_percent is not None and self.discount_amount is not None:
            raise ValueError("Specify either discount_percent or discount_amount, not both")
        return self


class SalesLineCalculated(BaseModel):
    """Server-calculated result for one line — never trust a client-supplied
    equivalent of these values (§60)."""

    product_id: str
    quantity: str
    uom_id: str
    unit_price: str
    gross_amount: str
    discount_amount: str
    taxable_amount: str
    gst_rate: str
    cgst_amount: str
    sgst_amount: str
    igst_amount: str
    line_total: str


class DocumentTotals(BaseModel):
    """Server-calculated document-level totals — sum of line results."""

    subtotal: str
    total_discount: str
    total_taxable: str
    total_cgst: str
    total_sgst: str
    total_igst: str
    grand_total: str
