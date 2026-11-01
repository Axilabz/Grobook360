from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings
from app.core.validators import is_valid_email, is_valid_gstin, is_valid_phone, is_valid_pin_code, is_valid_state_code


class OrganizationDetails(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    business_type: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state_code: str
    pin_code: str
    gstin: str | None = None

    @field_validator("state_code")
    @classmethod
    def _validate_state_code(cls, value: str) -> str:
        if not is_valid_state_code(value):
            raise ValueError("Invalid state code")
        return value

    @field_validator("pin_code")
    @classmethod
    def _validate_pin_code(cls, value: str) -> str:
        if not is_valid_pin_code(value):
            raise ValueError("Invalid PIN code")
        return value

    @field_validator("gstin")
    @classmethod
    def _validate_gstin(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_gstin(value):
            raise ValueError("Invalid GSTIN format")
        return value


class OwnerAccountDetails(BaseModel):
    # Email is mandatory: FRD FR-SU-04 lists it as a "Must"-priority captured
    # field at sign-up, and Database Design v3.0 marks user.email NOT NULL —
    # both baseline sources agree, so this is NOT a silently-invented rule.
    name: str | None = Field(default=None, max_length=200)
    phone: str
    email: str
    password: str
    confirm_password: str

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        if not is_valid_phone(value):
            raise ValueError("Phone must be exactly 10 numeric digits")
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not is_valid_email(value):
            raise ValueError("Invalid email format")
        return value

    @model_validator(mode="after")
    def _validate_password(self) -> "OwnerAccountDetails":
        settings = get_settings()
        if len(self.password) < settings.password_min_length:
            raise ValueError(
                f"Password must be at least {settings.password_min_length} characters "
                "(exact complexity policy is a pending BA/product decision)"
            )
        if self.password != self.confirm_password:
            raise ValueError("Password and confirmation do not match")
        return self


class SignUpRequest(BaseModel):
    organization: OrganizationDetails
    owner: OwnerAccountDetails


class SignUpResult(BaseModel):
    tenant_id: str
    owner_user_id: str
    status: str
