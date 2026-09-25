"""Invoice Template Configuration request/response schemas.

`logo_data_uri` on the update request is deliberately NOT accepted here
— logo upload goes through its own dedicated multipart endpoint
(`POST /configuration/business-logo`) so a plain color/toggle save can
never accidentally also replace the logo, and so upload-specific
validation (content-type/size) has one obvious place to live.
"""

import re

from pydantic import BaseModel, Field, field_validator

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_hex(value: str) -> str:
    if not _HEX_COLOR.match(value):
        raise ValueError("must be a 6-digit hex color, e.g. #2563EB")
    return value.upper()


class InvoiceTemplateConfigRequest(BaseModel):
    template_id: str = Field(pattern="^(CLASSIC|MODERN|COMPACT)$")
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    table_header_color: str

    show_logo: bool
    show_business_address: bool
    show_gstin: bool
    show_customer_gstin: bool
    show_hsn: bool
    show_discount: bool
    show_tax_breakup: bool
    show_bank_details: bool
    show_terms: bool
    show_amount_in_words: bool
    show_round_off: bool

    terms_text: str | None = Field(default=None, max_length=2000)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_account_name: str | None = Field(default=None, max_length=200)
    bank_account_number: str | None = Field(default=None, max_length=50)
    bank_ifsc: str | None = Field(default=None, max_length=20)
    bank_upi_id: str | None = Field(default=None, max_length=100)

    expected_row_version: int

    @field_validator("primary_color", "secondary_color", "accent_color", "text_color", "table_header_color")
    @classmethod
    def _validate_colors(cls, value: str) -> str:
        return _validate_hex(value)
