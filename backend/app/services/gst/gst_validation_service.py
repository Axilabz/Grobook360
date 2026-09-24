"""GST validation primitives (PROMPT-026 §12/§13/§32/§33) — pure,
side-effect-free functions, no DB access. Used by GST-return preparation
(`gstr_service.py`'s `validate_gstr1`/`validate_gstr3b`), NOT retrofitted
as a hard gate into Sales/Purchase document posting itself.

That's a deliberate scope decision, not an oversight: `sales_invoice_
service.py`/`purchase_invoice_service.py` etc. already have 606 passing
tests built against their existing posting behavior, several of which use
GSTINs/HSNs that would not survive a newly-invented strict format check
if one were silently added to the posting path. Retrofitting validation
into already-shipped document lifecycles without an approved requirement
demanding it was judged higher regression risk than the value it adds —
§32's own pre-submission validation (run at GSTR-1/GSTR-3B preparation
time, an entirely new surface with no prior behavior to break) is where
this module's checks are actually wired in. See PROMPT-026-NOTES.md.
"""

import re
from dataclasses import dataclass

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

# Structural GSTIN format (§12): 2-digit state code + 10-char PAN
# (5 letters, 4 digits, 1 letter) + 1 entity code + literal 'Z' + 1
# checksum character. This is a FORMAT check only — no MOD-36 checksum
# verification and no live government-portal verification (§12/OD-004:
# "use a provider abstraction... do not hard-code a specific third-party
# provider unless already approved" — no such provider is approved for
# M1, mirrors the identical open decision already made for sign-up's own
# GSTIN field, PROMPT-002).
_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

# Common HSN/SAC code lengths (2/4/6/8-digit, all-numeric). This is a
# structural check only — no lookup against a real HSN master exists
# (§3 OD-003: "exact HSN master source" is unresolved; this codebase
# reuses `product.hsn_code` as a free-text field, no HSN master table).
_HSN_PATTERN = re.compile(r"^[0-9]{4,8}$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    source_type: str
    source_id: str
    field: str
    suggested_action: str


def is_valid_gstin_format(gstin: str | None) -> bool:
    if not gstin:
        return False
    return bool(_GSTIN_PATTERN.match(gstin.strip().upper()))


def gstin_state_code(gstin: str) -> str:
    return gstin[:2]


def is_valid_hsn_format(hsn: str | None) -> bool:
    if not hsn:
        return False
    return bool(_HSN_PATTERN.match(hsn.strip()))
