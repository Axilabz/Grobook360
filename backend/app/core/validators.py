"""Reusable field validators (PROMPT-001 S17 foundation, extended in PROMPT-002).

GSTIN and phone format rules are public, well-defined formats (not business
decisions) — safe to hard-code here. Business meaning of a valid value (e.g.
whether it's mandatory) stays a product decision made by the caller.
"""

import re

# Standard 15-character GSTIN: 2-digit state code, 10-char PAN, entity code,
# 'Z' by convention, 1 checksum character.
_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

# FRD FR-SU-05 / legacy FRD: phone is 10 numeric digits.
_PHONE_PATTERN = re.compile(r"^[0-9]{10}$")

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PIN_CODE_PATTERN = re.compile(r"^[0-9]{6}$")

# ISO 3166-2:IN state codes are not enumerated in the available baseline
# documents; GST state codes (2-digit numeric, 01-38 range used by GSTIN) are
# used here as a practical placeholder validation. Exact state list/format for
# non-GST address state entry remains a BA/PRODUCT DECISION if stricter
# validation is required.
_STATE_CODE_PATTERN = re.compile(r"^[0-9]{2}$")

# HSN (goods) codes are 4/6/8 numeric digits and SAC (services) codes are 6
# digits under GST — format-only check (PROMPT-009 S13: this is not external
# HSN master verification, just a structural sanity check).
_HSN_PATTERN = re.compile(r"^[0-9]{4}$|^[0-9]{6}$|^[0-9]{8}$")

# SKU: uppercase alphanumeric plus hyphen/underscore, 1-50 chars (matches the
# product.sku column length). Auto-uppercased by the caller before checking.
_SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,49}$")

# Standard 10-character Indian PAN: 5 letters, 4 digits, 1 letter.
_PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# Standard 11-character bank IFSC code: 4-letter bank code, '0', 6
# alphanumeric branch code.
_IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def is_valid_gstin(value: str) -> bool:
    return bool(_GSTIN_PATTERN.match(value))


def is_valid_phone(value: str) -> bool:
    return bool(_PHONE_PATTERN.match(value))


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_PATTERN.match(value))


def is_valid_pin_code(value: str) -> bool:
    return bool(_PIN_CODE_PATTERN.match(value))


def is_valid_state_code(value: str) -> bool:
    return bool(_STATE_CODE_PATTERN.match(value))


def is_valid_hsn(value: str) -> bool:
    return bool(_HSN_PATTERN.match(value))


def is_valid_sku(value: str) -> bool:
    return bool(_SKU_PATTERN.match(value))


def is_valid_pan(value: str) -> bool:
    return bool(_PAN_PATTERN.match(value))


def is_valid_ifsc(value: str) -> bool:
    return bool(_IFSC_PATTERN.match(value))
