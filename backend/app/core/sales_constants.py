"""Sales & Billing shared constants (PROMPT-011).

Pure vocabulary, not a DB-backed enum — no concrete Sales document table
exists yet (Estimate/Sales Order/Delivery Challan/Sales Invoice/Sales
Return/Credit Note/Debit Note are each a future prompt's own scope, per
this prompt's explicit "do not implement full workflows" boundary). These
constants exist so every future document-type prompt uses the same
vocabulary instead of each inventing its own strings.
"""

# --- Document types (§5) ---
ESTIMATE = "ESTIMATE"
SALES_ORDER = "SALES_ORDER"
DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
SALES_INVOICE = "SALES_INVOICE"
SALES_RETURN = "SALES_RETURN"
CREDIT_NOTE = "CREDIT_NOTE"
DEBIT_NOTE = "DEBIT_NOTE"

SALES_DOCUMENT_TYPES = frozenset(
    {ESTIMATE, SALES_ORDER, DELIVERY_CHALLAN, SALES_INVOICE, SALES_RETURN, CREDIT_NOTE, DEBIT_NOTE}
)

# --- Generic lifecycle statuses (§22) ---
# Not every document type supports every status — each future prompt picks
# its own applicable subset from this shared vocabulary rather than
# inventing new strings per document type.
DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
POSTED = "POSTED"
CANCELLED = "CANCELLED"
VOID = "VOID"

SALES_DOCUMENT_STATUSES = frozenset({DRAFT, CONFIRMED, POSTED, CANCELLED, VOID})

# --- GST treatment (§13/§15) ---
INTRA_STATE = "INTRA_STATE"  # CGST + SGST
INTER_STATE = "INTER_STATE"  # IGST

# --- Which document types reduce/increase stock, and how (§25-§29) ---
# Documented here once so every future prompt implements the identical
# rule rather than re-deriving it: Estimate and Sales Order never move
# stock; Delivery Challan and direct Sales Invoice reduce it (STOCK_OUT);
# Sales Return increases it (STOCK_IN). Credit/Debit Note stock effect (if
# any) is that document type's own decision — not prescribed here.
STOCK_EFFECT_BY_DOCUMENT_TYPE = {
    ESTIMATE: None,
    SALES_ORDER: None,
    DELIVERY_CHALLAN: "STOCK_OUT",
    SALES_INVOICE: "STOCK_OUT",
    SALES_RETURN: "STOCK_IN",
}
