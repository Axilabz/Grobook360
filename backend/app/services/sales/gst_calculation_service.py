"""GST Calculation Service (PROMPT-011).

The single, reusable place every future Sales document type computes
line/document tax amounts — §14: "Do NOT hardcode complex GST rules into
Sales screens... Sales should call/use the approved GST calculation
service." Pure functions, no DB access, no side effects: callers pass in
the already-resolved GST rate (from Product Master at transaction time —
never re-derived from a possibly-since-changed product row, per §21's
GST-snapshot requirement) and the two state codes; this service only does
arithmetic.

Rounding: money amounts round to 2 decimal places using ROUND_HALF_UP
(standard commercial rounding — Python's Decimal default, ROUND_HALF_EVEN,
is not the convention Indian GST invoicing uses). This is a documented
decision (§41 rounding policy was otherwise unresolved) — see
PROMPT-011-NOTES.md.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.sales_constants import INTER_STATE, INTRA_STATE

_MONEY_QUANT = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def determine_gst_treatment(*, supplier_state_code: str | None, customer_state_code: str | None) -> str:
    """§15: place-of-supply treatment. A missing customer state is treated
    as intra-state (the conservative default when place-of-supply cannot be
    determined) — this is a documented interpretation, not a claim that
    the general Place-of-Supply rule set has been fully implemented; a
    dedicated GST module may need to refine this later."""
    if not customer_state_code or not supplier_state_code:
        return INTRA_STATE
    return INTRA_STATE if customer_state_code == supplier_state_code else INTER_STATE


@dataclass(frozen=True)
class LineCalculationResult:
    gross_amount: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    line_total: Decimal


def calculate_line(
    *,
    quantity: Decimal,
    unit_price: Decimal,
    discount_percent: Decimal | None,
    discount_amount: Decimal | None,
    gst_rate: Decimal,
    gst_treatment: str,
) -> LineCalculationResult:
    """§11-13/§40: Quantity x Unit Price -> Gross; Gross - Discount ->
    Taxable; Taxable + GST -> Line Total. Discount is applied before GST
    (Selling Price is tax-exclusive — §3.1/§3.2)."""
    gross_amount = quantity * unit_price

    if discount_amount is not None:
        discount = discount_amount
    elif discount_percent is not None:
        discount = gross_amount * discount_percent / Decimal("100")
    else:
        discount = Decimal("0")

    taxable_amount = gross_amount - discount
    if taxable_amount < 0:
        taxable_amount = Decimal("0")  # discount capped at gross amount, never a negative taxable value

    gst_amount = taxable_amount * gst_rate / Decimal("100")

    if gst_treatment == INTER_STATE:
        cgst = Decimal("0")
        sgst = Decimal("0")
        igst = gst_amount
    else:
        half = gst_amount / Decimal("2")
        cgst = half
        sgst = half
        igst = Decimal("0")

    taxable_amount = _round_money(taxable_amount)
    cgst = _round_money(cgst)
    sgst = _round_money(sgst)
    igst = _round_money(igst)
    line_total = taxable_amount + cgst + sgst + igst

    return LineCalculationResult(
        gross_amount=_round_money(gross_amount),
        discount_amount=_round_money(discount),
        taxable_amount=taxable_amount,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        line_total=line_total,
    )


@dataclass(frozen=True)
class DocumentTotalsResult:
    subtotal: Decimal
    total_discount: Decimal
    total_taxable: Decimal
    total_cgst: Decimal
    total_sgst: Decimal
    total_igst: Decimal
    grand_total: Decimal


def calculate_document_totals(lines: list[LineCalculationResult]) -> DocumentTotalsResult:
    """§40: document total = sum of line taxable amounts + tax totals. No
    unapproved charges/fees/round-off are added here — round-off is an
    explicit open decision (§74 Q24), not silently introduced."""
    subtotal = sum((line.gross_amount for line in lines), Decimal("0"))
    total_discount = sum((line.discount_amount for line in lines), Decimal("0"))
    total_taxable = sum((line.taxable_amount for line in lines), Decimal("0"))
    total_cgst = sum((line.cgst_amount for line in lines), Decimal("0"))
    total_sgst = sum((line.sgst_amount for line in lines), Decimal("0"))
    total_igst = sum((line.igst_amount for line in lines), Decimal("0"))
    grand_total = total_taxable + total_cgst + total_sgst + total_igst

    return DocumentTotalsResult(
        subtotal=_round_money(subtotal),
        total_discount=_round_money(total_discount),
        total_taxable=_round_money(total_taxable),
        total_cgst=_round_money(total_cgst),
        total_sgst=_round_money(total_sgst),
        total_igst=_round_money(total_igst),
        grand_total=_round_money(grand_total),
    )
