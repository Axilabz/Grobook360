"""PROMPT-011 unit tests for the GST Calculation Service — pure, no DB."""

from decimal import Decimal

from app.core.sales_constants import INTER_STATE, INTRA_STATE
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)


def test_determine_gst_treatment_same_state_is_intra_state():
    assert determine_gst_treatment(supplier_state_code="33", customer_state_code="33") == INTRA_STATE


def test_determine_gst_treatment_different_state_is_inter_state():
    assert determine_gst_treatment(supplier_state_code="33", customer_state_code="27") == INTER_STATE


def test_determine_gst_treatment_missing_customer_state_defaults_intra():
    assert determine_gst_treatment(supplier_state_code="33", customer_state_code=None) == INTRA_STATE


def test_calculate_line_intra_state_splits_cgst_sgst():
    result = calculate_line(
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percent=None,
        discount_amount=None,
        gst_rate=Decimal("18"),
        gst_treatment=INTRA_STATE,
    )
    assert result.gross_amount == Decimal("1000.00")
    assert result.taxable_amount == Decimal("1000.00")
    assert result.cgst_amount == Decimal("90.00")
    assert result.sgst_amount == Decimal("90.00")
    assert result.igst_amount == Decimal("0.00")
    assert result.line_total == Decimal("1180.00")


def test_calculate_line_inter_state_uses_igst_only():
    result = calculate_line(
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percent=None,
        discount_amount=None,
        gst_rate=Decimal("18"),
        gst_treatment=INTER_STATE,
    )
    assert result.cgst_amount == Decimal("0.00")
    assert result.sgst_amount == Decimal("0.00")
    assert result.igst_amount == Decimal("180.00")
    assert result.line_total == Decimal("1180.00")


def test_calculate_line_discount_amount_applied_before_gst():
    # §12 worked example: Gross 1000, discount 100 -> taxable 900, GST 18% = 162.
    result = calculate_line(
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percent=None,
        discount_amount=Decimal("100"),
        gst_rate=Decimal("18"),
        gst_treatment=INTRA_STATE,
    )
    assert result.taxable_amount == Decimal("900.00")
    assert result.cgst_amount == Decimal("81.00")
    assert result.sgst_amount == Decimal("81.00")
    assert result.line_total == Decimal("1062.00")


def test_calculate_line_discount_percent():
    result = calculate_line(
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percent=Decimal("10"),
        discount_amount=None,
        gst_rate=Decimal("18"),
        gst_treatment=INTRA_STATE,
    )
    assert result.discount_amount == Decimal("100.00")
    assert result.taxable_amount == Decimal("900.00")


def test_calculate_line_discount_cannot_exceed_gross():
    result = calculate_line(
        quantity=Decimal("1"),
        unit_price=Decimal("50"),
        discount_percent=None,
        discount_amount=Decimal("999"),
        gst_rate=Decimal("18"),
        gst_treatment=INTRA_STATE,
    )
    assert result.taxable_amount == Decimal("0.00")
    assert result.line_total == Decimal("0.00")


def test_calculate_line_zero_gst_rate():
    result = calculate_line(
        quantity=Decimal("5"),
        unit_price=Decimal("20"),
        discount_percent=None,
        discount_amount=None,
        gst_rate=Decimal("0"),
        gst_treatment=INTRA_STATE,
    )
    assert result.cgst_amount == Decimal("0.00")
    assert result.line_total == Decimal("100.00")


def test_calculate_document_totals_sums_lines():
    line1 = calculate_line(
        quantity=Decimal("10"), unit_price=Decimal("100"), discount_percent=None,
        discount_amount=None, gst_rate=Decimal("18"), gst_treatment=INTRA_STATE,
    )
    line2 = calculate_line(
        quantity=Decimal("2"), unit_price=Decimal("50"), discount_percent=None,
        discount_amount=None, gst_rate=Decimal("5"), gst_treatment=INTRA_STATE,
    )
    totals = calculate_document_totals([line1, line2])
    assert totals.subtotal == Decimal("1100.00")
    assert totals.total_taxable == Decimal("1100.00")
    assert totals.grand_total == line1.line_total + line2.line_total
