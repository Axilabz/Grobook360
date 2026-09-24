"""Purchase & Billing shared constants (PROMPT-019).

Mirrors `app.core.sales_constants`'s exact role for the Sales domain —
pure vocabulary every Purchase document-type service imports, rather
than each inventing its own strings.
"""

# --- Document types (used as document_number_sequence.document_type) ---
PURCHASE_ORDER = "PURCHASE_ORDER"
GOODS_RECEIPT = "GOODS_RECEIPT"
PURCHASE_INVOICE = "PURCHASE_INVOICE"
PURCHASE_RETURN = "PURCHASE_RETURN"

PURCHASE_DOCUMENT_TYPES = frozenset({PURCHASE_ORDER, GOODS_RECEIPT, PURCHASE_INVOICE, PURCHASE_RETURN})

# PROMPT-021 §23/§25: the stock_ledger_entry.source_type used for a
# confirmed Goods Receipt's compensating STOCK_OUT reversal on approved
# cancellation. Deliberately DISTINCT from GOODS_RECEIPT (not just a
# second entry with the same source_type) — the reversal's source_id is
# the SAME goods_receipt_line.id as the original STOCK_IN, and
# `uq_stock_ledger_entry_source` is unique on (tenant_id, source_type,
# source_id), so reusing GOODS_RECEIPT here would collide with the
# original entry instead of coexisting alongside it (INVARIANT 7: the
# original STOCK_IN is never edited or deleted, only compensated).
GOODS_RECEIPT_REVERSAL = "GOODS_RECEIPT_REVERSAL"

# PROMPT-022 §33-34: same pattern, one level up the chain — the
# compensating STOCK_OUT reversal for a cancelled DIRECT Purchase
# Invoice (the only invoice type that ever creates its own Stock IN).
PURCHASE_INVOICE_REVERSAL = "PURCHASE_INVOICE_REVERSAL"

# PROMPT-023 §33-35: same pattern, for a cancelled CONFIRMED Purchase
# Return — the compensating STOCK_IN reversal (goods physically coming
# back onto the shelf because the return itself is being undone). Same
# source_id as the original STOCK_OUT (source_type=PURCHASE_RETURN),
# coexists under `uq_stock_ledger_entry_source` without colliding.
PURCHASE_RETURN_REVERSAL = "PURCHASE_RETURN_REVERSAL"

# --- Which document types move stock, and how (§4/§10-13) ---
# Purchase Order never moves stock; Goods Receipt and a direct (no prior
# GR) Purchase Invoice create STOCK_IN; Purchase Return creates STOCK_OUT.
# A GR-based Purchase Invoice creates NO stock movement of its own — the
# source GR already moved it (mirrors Sales's DC-based-invoice rule,
# PROMPT-015 §2, exactly).
STOCK_EFFECT_BY_DOCUMENT_TYPE = {
    PURCHASE_ORDER: None,
    GOODS_RECEIPT: "STOCK_IN",
    PURCHASE_INVOICE: "STOCK_IN",  # only for the DIRECT (no source GR) case
    PURCHASE_RETURN: "STOCK_OUT",
}
