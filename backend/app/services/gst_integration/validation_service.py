"""E-Invoice / E-Way Bill pre-validation (PROMPT-018 §9/§19).

Validates required data BEFORE any external submission — §9 explicit
requirement: "the system must fail BEFORE external submission when
mandatory data is missing," with actionable messages (never a raw
provider payload error). Returns a plain list of human-readable
messages; an empty list means "ready to submit."

Only checks fields this codebase's approved GST calculation/Sales
Invoice foundation already treats as mandatory (seller GSTIN, place of
supply, line HSN, positive taxable value) — no invented schema-specific
field requirements beyond what §9's own baseline lists as generally
applicable.
"""

from decimal import Decimal

from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.tenant import Tenant


def validate_einvoice_data(
    *, tenant: Tenant, invoice: SalesInvoice, lines: list[SalesInvoiceLine]
) -> list[str]:
    errors: list[str] = []

    if not tenant.gstin:
        errors.append("E-Invoice cannot be generated because the seller (your business) has no GSTIN on file.")
    if not invoice.place_of_supply_state_code:
        errors.append("E-Invoice cannot be generated because the invoice has no place of supply recorded.")
    if not invoice.billing_address:
        errors.append("E-Invoice cannot be generated because the customer billing address is missing.")
    if not lines:
        errors.append("E-Invoice cannot be generated because the invoice has no line items.")

    for index, line in enumerate(lines, start=1):
        if not line.hsn_code:
            errors.append(f"E-Invoice cannot be generated because HSN is missing for line item {index}.")
        if line.quantity <= 0:
            errors.append(f"E-Invoice cannot be generated because line item {index} has an invalid quantity.")
        if line.taxable_amount < 0:
            errors.append(f"E-Invoice cannot be generated because line item {index} has an invalid taxable value.")

    if invoice.grand_total <= Decimal("0"):
        errors.append("E-Invoice cannot be generated because the invoice total is zero or negative.")

    return errors


def validate_eway_bill_data(
    *,
    tenant: Tenant,
    invoice: SalesInvoice,
    lines: list[SalesInvoiceLine],
    transport_mode: str | None,
    vehicle_number: str | None,
    transporter_id: str | None,
) -> list[str]:
    errors: list[str] = []

    if not tenant.gstin:
        errors.append("E-Way Bill cannot be generated because the seller (your business) has no GSTIN on file.")
    if not invoice.place_of_supply_state_code:
        errors.append("E-Way Bill cannot be generated because the invoice has no place of supply recorded.")
    if not invoice.shipping_address and not invoice.billing_address:
        errors.append("E-Way Bill cannot be generated because no delivery/shipping address is available.")
    if not lines:
        errors.append("E-Way Bill cannot be generated because the invoice has no line items.")

    for index, line in enumerate(lines, start=1):
        if not line.hsn_code:
            errors.append(f"E-Way Bill cannot be generated because HSN is missing for line item {index}.")

    if not transport_mode:
        errors.append("E-Way Bill cannot be generated because the transport mode is missing.")
    elif transport_mode == "ROAD" and not vehicle_number and not transporter_id:
        errors.append(
            "E-Way Bill cannot be generated because a vehicle number or transporter ID is required for road transport."
        )

    return errors
