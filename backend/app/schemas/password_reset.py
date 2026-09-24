from pydantic import BaseModel, field_validator, model_validator

from app.core.config import get_settings
from app.core.validators import is_valid_email


class ForgotPasswordRequest(BaseModel):
    # Recovery identifier is email (PROMPT-004 S4 decision — see
    # PROMPT-004-NOTES.md): OTP-to-phone is explicitly out of scope, so a
    # link-based channel needs email, the only other stored identifier.
    recovery_identifier: str

    @field_validator("recovery_identifier")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        if not is_valid_email(value):
            raise ValueError("Invalid email format")
        return value


class ValidateResetTokenRequest(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

    @model_validator(mode="after")
    def _validate_password(self) -> "ResetPasswordRequest":
        settings = get_settings()
        # Same policy as sign-up (PROMPT-002/PROMPT-004 S14: use the existing
        # policy, don't create a conflicting one).
        if len(self.new_password) < settings.password_min_length:
            raise ValueError(f"Password must be at least {settings.password_min_length} characters")
        if self.new_password != self.confirm_password:
            raise ValueError("Password and confirmation do not match")
        return self
