"""Supplier Management request/response schemas (PROMPT-008).

Field requiredness follows FR-SUPP-01 (Confirmed): company name, contact
person and phone are mandatory; email and GSTIN are optional. state_code is
required only when gstin is supplied (structurally encoded in the GSTIN's
first two digits — FR-SUPP-03) and is auto-derived from it when omitted.

No region/gps_location/credit_limit fields exist here — FR-SUPP-02
explicitly excludes them for Supplier (they are Customer-only per PROMPT-007).
"""

from pydantic import BaseModel, Field, model_validator

from app.core.validators import (
    is_valid_email,
    is_valid_gstin,
    is_valid_phone,
    is_valid_pin_code,
    is_valid_state_code,
)


class SupplierListItem(BaseModel):
    id: str
    supplier_code: str
    name: str
    contact_person: str
    phone: str | None
    email: str | None
    gstin: str | None
    state_code: str | None
    address: str | None
    city: str | None
    pincode: str | None
    credit_terms_days: int
    balance: str
    status: str
    created_at: str
    updated_at: str
    row_version: int


class SupplierDetail(SupplierListItem):
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


class CreateSupplierRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_person: str = Field(min_length=1, max_length=200)
    phone: str
    email: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    pincode: str | None = None
    credit_terms_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> "CreateSupplierRequest":
        if not is_valid_phone(self.phone):
            raise ValueError("Phone must be exactly 10 numeric digits")
        if self.email is not None and not is_valid_email(self.email):
            raise ValueError("Invalid email format")
        if self.pincode is not None and not is_valid_pin_code(self.pincode):
            raise ValueError("Pincode must be exactly 6 numeric digits")
        self.gstin, self.state_code = _validate_gst_fields(self.gstin, self.state_code)
        return self


class UpdateSupplierRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_person: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    pincode: str | None = None
    credit_terms_days: int | None = Field(default=None, ge=0)
    expected_row_version: int

    # The router dumps this model with exclude_unset=True: a field omitted
    # from the request body is left untouched, while a field explicitly sent
    # as null clears it (see app/api/v1/suppliers.py).
    @model_validator(mode="after")
    def _validate(self) -> "UpdateSupplierRequest":
        for required_field in ("name", "contact_person", "phone"):
            if required_field in self.model_fields_set and getattr(self, required_field) is None:
                raise ValueError(f"{required_field} cannot be cleared")
        if self.phone is not None and not is_valid_phone(self.phone):
            raise ValueError("Phone must be exactly 10 numeric digits")
        if self.email is not None and not is_valid_email(self.email):
            raise ValueError("Invalid email format")
        if self.pincode is not None and not is_valid_pin_code(self.pincode):
            raise ValueError("Pincode must be exactly 6 numeric digits")
        # GSTIN/state cross-consistency requires the *current* stored value
        # for whichever of the two isn't being changed here — deferred to
        # the service layer, same as UpdateCustomerRequest.
        if self.gstin is not None and not is_valid_gstin(self.gstin):
            raise ValueError("Enter a valid GSTIN")
        if self.state_code is not None and not is_valid_state_code(self.state_code):
            raise ValueError("Invalid state code")
        return self


class ActivateDeactivateSupplierRequest(BaseModel):
    expected_row_version: int
