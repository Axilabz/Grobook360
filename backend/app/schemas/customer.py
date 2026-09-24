"""Customer Management request/response schemas (PROMPT-007).

Field requiredness follows FR-CUST-01 (Confirmed): business name, owner
name and phone are mandatory; email and GSTIN are optional. state_code is
required only when gstin is supplied (it is structurally encoded in the
GSTIN's first two digits — FR-CUST-04) and is auto-derived from it when
omitted, rather than forcing the caller to repeat information already in
the GSTIN.
"""

from pydantic import BaseModel, Field, model_validator

from app.core.validators import (
    is_valid_email,
    is_valid_gstin,
    is_valid_phone,
    is_valid_pin_code,
    is_valid_state_code,
)


class CustomerListItem(BaseModel):
    id: str
    customer_code: str
    name: str
    owner_name: str
    phone: str | None
    email: str | None
    gstin: str | None
    state_code: str | None
    address: str | None
    city: str | None
    pincode: str | None
    region: str | None
    gps_location: str | None
    credit_limit: str
    payment_terms_days: int
    balance: str
    # Advisory only (FR-CUST-06, "Should" — hard-blocking left explicitly
    # open by OQ-009). Never used to prevent anything in this module.
    is_over_credit_limit: bool
    status: str
    created_at: str
    updated_at: str
    row_version: int


class CustomerDetail(CustomerListItem):
    pass


def _validate_gst_fields(gstin: str | None, state_code: str | None) -> tuple[str | None, str | None]:
    if gstin is None:
        if state_code is not None and not is_valid_state_code(state_code):
            raise ValueError("Invalid state code")
        return gstin, state_code

    if not is_valid_gstin(gstin):
        raise ValueError("Enter a valid GSTIN")

    gstin_state = gstin[:2]
    if state_code is None:
        state_code = gstin_state
    elif state_code != gstin_state:
        raise ValueError("State does not match the state encoded in the GSTIN")
    return gstin, state_code


class CreateCustomerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=200)
    phone: str
    email: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    pincode: str | None = None
    region: str | None = Field(default=None, max_length=100)
    gps_location: str | None = Field(default=None, max_length=500)
    credit_limit: float = Field(default=0, ge=0)
    payment_terms_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> "CreateCustomerRequest":
        if not is_valid_phone(self.phone):
            raise ValueError("Phone must be exactly 10 numeric digits")
        if self.email is not None and not is_valid_email(self.email):
            raise ValueError("Invalid email format")
        if self.pincode is not None and not is_valid_pin_code(self.pincode):
            raise ValueError("Pincode must be exactly 6 numeric digits")
        self.gstin, self.state_code = _validate_gst_fields(self.gstin, self.state_code)
        return self


class UpdateCustomerRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    owner_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    pincode: str | None = None
    region: str | None = Field(default=None, max_length=100)
    gps_location: str | None = Field(default=None, max_length=500)
    credit_limit: float | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0)
    expected_row_version: int

    # Unlike UpdateUserRequest (PROMPT-005), the router dumps this model with
    # exclude_unset=True: a field omitted from the request body is left
    # untouched, while a field explicitly sent as null clears it. Format
    # validation below only runs against fields that were actually supplied.
    @model_validator(mode="after")
    def _validate(self) -> "UpdateCustomerRequest":
        # name/owner_name/phone are NOT NULL-backed (or app-required) fields —
        # explicitly nulling them would either violate the DB constraint or
        # contradict FR-CUST-01's required-field list, so reject rather than
        # letting a bad request surface as an opaque 500 at flush time.
        for required_field in ("name", "owner_name", "phone"):
            if required_field in self.model_fields_set and getattr(self, required_field) is None:
                raise ValueError(f"{required_field} cannot be cleared")
        if self.phone is not None and not is_valid_phone(self.phone):
            raise ValueError("Phone must be exactly 10 numeric digits")
        if self.email is not None and not is_valid_email(self.email):
            raise ValueError("Invalid email format")
        if self.pincode is not None and not is_valid_pin_code(self.pincode):
            raise ValueError("Pincode must be exactly 6 numeric digits")
        # GSTIN/state cross-consistency requires knowing the *current* stored
        # value for whichever of the two isn't being changed here, so it's
        # deferred to the service layer (which has the existing row) rather
        # than done in this schema — only independent per-field format is
        # checked at this layer.
        if self.gstin is not None and not is_valid_gstin(self.gstin):
            raise ValueError("Enter a valid GSTIN")
        if self.state_code is not None and not is_valid_state_code(self.state_code):
            raise ValueError("Invalid state code")
        return self


class ActivateDeactivateCustomerRequest(BaseModel):
    expected_row_version: int
