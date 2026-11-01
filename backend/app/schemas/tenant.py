"""Company Profile request/response schemas.

Exposes every `tenant` column the frontend's Company Profile screen
(`ViewCompany.tsx`) displays, now that migration 0033 added PAN, business
type, phone/email/website, and bank detail columns (previously, those
fields had no backend column at all and the screen showed hardcoded,
unsaved mock data).
"""

from pydantic import BaseModel, Field, model_validator

from app.core.validators import (
    is_valid_email,
    is_valid_gstin,
    is_valid_ifsc,
    is_valid_pan,
    is_valid_phone,
    is_valid_pin_code,
    is_valid_state_code,
)


class TenantProfileResponse(BaseModel):
    id: str
    tenant_code: str
    business_name: str
    gstin: str | None
    state_code: str | None
    address_line1: str | None
    city: str | None
    pin_code: str | None
    pan: str | None
    business_type: str | None
    phone: str | None
    email: str | None
    website: str | None
    bank_name: str | None
    bank_account_number: str | None
    bank_account_holder_name: str | None
    bank_ifsc: str | None
    bank_branch_name: str | None
    bank_account_type: str | None
    bank_upi_id: str | None
    financial_year_start_month: int
    status: str
    row_version: int


class UpdateTenantProfileRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    gstin: str | None = None
    state_code: str | None = None
    address_line1: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    pin_code: str | None = None
    pan: str | None = None
    business_type: str | None = Field(default=None, max_length=50)
    phone: str | None = None
    email: str | None = None
    website: str | None = Field(default=None, max_length=255)
    bank_name: str | None = Field(default=None, max_length=100)
    bank_account_number: str | None = Field(default=None, max_length=30)
    bank_account_holder_name: str | None = Field(default=None, max_length=200)
    bank_ifsc: str | None = None
    bank_branch_name: str | None = Field(default=None, max_length=100)
    bank_account_type: str | None = Field(default=None, max_length=20)
    bank_upi_id: str | None = Field(default=None, max_length=100)
    expected_row_version: int

    @model_validator(mode="after")
    def _validate(self) -> "UpdateTenantProfileRequest":
        self.business_name = self.business_name.strip()
        if not self.business_name:
            raise ValueError("Organization name is required")
        if self.pin_code is not None and not is_valid_pin_code(self.pin_code):
            raise ValueError("Pincode must be exactly 6 numeric digits")
        if self.gstin is not None and not is_valid_gstin(self.gstin):
            raise ValueError("Enter a valid GSTIN")
        if self.state_code is not None and not is_valid_state_code(self.state_code):
            raise ValueError("Invalid state code")
        if self.pan is not None and not is_valid_pan(self.pan):
            raise ValueError("Enter a valid PAN (e.g. ABCDE1234F)")
        if self.phone is not None and not is_valid_phone(self.phone):
            raise ValueError("Phone must be exactly 10 numeric digits")
        if self.email is not None and not is_valid_email(self.email):
            raise ValueError("Invalid email format")
        if self.bank_ifsc is not None and not is_valid_ifsc(self.bank_ifsc):
            raise ValueError("Enter a valid IFSC code (e.g. HDFC0001234)")
        return self
