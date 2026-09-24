from pydantic import BaseModel, Field, field_validator

from app.core.validators import is_valid_email, is_valid_phone

# Only tenant-scoped roles are assignable through tenant User Management.
# PLATFORM_ADMINISTRATOR is deliberately excluded — a normal tenant Owner must
# never be able to create or assign it (PROMPT-005 S15, CRITICAL).
ASSIGNABLE_ROLES = {"OWNER", "MANAGER", "SALESPERSON"}


class UserListItem(BaseModel):
    id: str
    name: str | None
    phone: str | None
    email: str
    role: str | None
    status: str
    created_at: str
    updated_at: str
    # Included in the list response (not just detail): the frontend needs it
    # to send If-Match/expected_row_version on activate/deactivate/edit
    # actions taken directly from the list, without a separate detail fetch.
    row_version: int


class UserDetail(UserListItem):
    pass


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str
    email: str
    role: str

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

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        if value not in ASSIGNABLE_ROLES:
            raise ValueError("Invalid role")
        return value


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = None
    role: str | None = None
    expected_row_version: int

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_email(value):
            raise ValueError("Invalid email format")
        return value

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str | None) -> str | None:
        if value is not None and value not in ASSIGNABLE_ROLES:
            raise ValueError("Invalid role")
        return value


class ActivateDeactivateRequest(BaseModel):
    expected_row_version: int
