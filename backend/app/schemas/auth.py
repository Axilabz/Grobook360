from pydantic import BaseModel, field_validator

from app.core.validators import is_valid_phone


class LoginRequest(BaseModel):
    login_identifier: str
    password: str

    @field_validator("login_identifier")
    @classmethod
    def _validate_login_identifier(cls, value: str) -> str:
        # FRD FR-SI-01: sign-in uses phone, not email/username (see
        # PROMPT-003-NOTES.md S5 precedence note).
        if not is_valid_phone(value):
            raise ValueError("Login identifier must be a valid 10-digit phone number")
        return value


class UserSummary(BaseModel):
    # No "name" field: PROMPT-003 S4 asks for one, but neither the Data
    # Dictionary's user table nor PROMPT-002's sign-up form has/captures a
    # personal display name (only phone/email/password_hash exist). Flagged as
    # a required schema change in PROMPT-003-NOTES.md rather than invented here.
    id: str
    phone: str
    email: str
    role: str | None


class TenantSummary(BaseModel):
    id: str
    tenant_code: str
    business_name: str


class LoginResponseData(BaseModel):
    user: UserSummary
    tenant: TenantSummary | None
    permissions: list[str]


class MeResponseData(BaseModel):
    user_id: str
    tenant_id: str | None
    # Added so a page refresh (which calls /auth/me, not /auth/login) can
    # still show the real tenant name in the header — previously only the
    # login response carried it, so the header fell back to a hardcoded
    # "Agin Crop" placeholder on every refresh regardless of who was
    # actually logged in.
    tenant: TenantSummary | None
    role: str | None
    permissions: list[str]
