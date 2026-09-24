"""GST Rule Engine & GST Reporting shared constants (PROMPT-026).

Pure vocabulary — no business logic here. `app.services.sales.
gst_calculation_service` (PROMPT-011) remains the ONE authoritative GST
CALCULATION engine (line/document totals, CGST+SGST vs IGST split,
discount-before-GST) and is reused as-is by every module; this file adds
the vocabulary needed for the GST REPORTING layer this prompt introduces
on top of it (§2's mandatory single-engine principle — calculation logic
is never duplicated, only its output is now also snapshotted for
reporting).
"""

# --- Direction (§27): which side of the tenant's own GST position a
# transaction affects. Reuses the same `SRC_*` source_type vocabulary as
# `app.core.accounting_constants` so a `gst_transaction.source_type` value
# is always identical to the corresponding `journal_entry.source_type`
# value for the same source document (§24 reconciliation depends on this).
OUTWARD = "OUTWARD"  # Sales Invoice, Sales Return, Credit Note, Debit Note
INWARD = "INWARD"  # Purchase Invoice, Purchase Return

# --- Event type (§17/§21, mirrors `app.core.accounting_constants`
# EVT_ORIGINAL/EVT_REVERSAL exactly): a REVERSAL is a brand-new snapshot
# row with negated amounts, never an edit to the ORIGINAL (§21 immutability).
EVT_ORIGINAL = "ORIGINAL"
EVT_REVERSAL = "REVERSAL"

GST_TRANSACTION_EVENT_TYPES = frozenset({EVT_ORIGINAL, EVT_REVERSAL})

# --- Classification (§11, B2B/B2C only — §11 explicitly says "do not
# invent additional classifications unless required"). Reuses the exact
# same string values `sales_invoice.customer_type` already stores
# (`app.models.sales_invoice.B2B`/`B2C`) rather than duplicating them.
B2B = "B2B"
B2C = "B2C"

GST_CLASSIFICATIONS = frozenset({B2B, B2C})
