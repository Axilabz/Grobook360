"""Product Master request/response schemas (PROMPT-009).

Field requiredness follows FR-PROD-01 (Confirmed): name, SKU and base unit
are mandatory. Cost Price/Selling Price/MRP are NOT NULL with a default of 0
in the baseline, so they're always present in responses but not required as
create input (default to 0, matching the column default).

`gst_rate` was originally optional (nullable in the approved baseline) but
is now a REQUIRED, closed-set field (user-requested follow-up) — GST
correctness downstream (Sales/Purchase document calculation, GSTR-1/3B
reporting) depends on every product having a real, valid slab rate rather
than silently defaulting to "no GST," so this is deliberately stricter than
the original baseline. Allowed values are the current standard GST slabs:
0, 3, 5, 12, 18, 28 — see `ALLOWED_GST_RATES` below, the single place this
set is defined (both Create/Update validate against it).

Deliberately absent: category/subcategory/brand/product_type/description
(not in the approved model — see migration 0010's docstring), and
reorder_level/stock_qty_cache/batch_no/expiry_date as INPUT fields (they
exist as read-only, always-zero-or-null display fields — see
ProductListItem/ProductDetail below — but are never accepted by
Create/UpdateProductRequest).

No enforcement of selling_price <= mrp: not defined by any approved source
(PROMPT-009 S25/S73 Q28) — left as an explicit open decision, not invented.
"""

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.validators import is_valid_hsn, is_valid_sku

ALLOWED_GST_RATES: frozenset[Decimal] = frozenset(
    Decimal(v) for v in ("0", "3", "5", "12", "18", "28")
)


def _validate_gst_rate(value: Decimal) -> Decimal:
    if value not in ALLOWED_GST_RATES:
        allowed = ", ".join(str(v) for v in sorted(ALLOWED_GST_RATES))
        raise ValueError(f"GST rate must be one of: {allowed}")
    # Quantize to the column's own 2-decimal-place scale (Numeric(5, 2)) here,
    # at validation time — not just implicitly after a DB round-trip. Without
    # this, a plain-scale input like "18" stays Decimal("18") in the
    # in-memory ORM object immediately after create/update, so the very next
    # API response would show "18" instead of "18.00" until the row is
    # re-fetched from Postgres. Same class of bug already found and fixed in
    # PROMPT-029's leave_service.py — fixed here the same way, at the source.
    return value.quantize(Decimal("0.01"))


class UnitRef(BaseModel):
    id: str
    code: str
    name: str


class SupplierRef(BaseModel):
    id: str
    name: str
    supplier_code: str
    phone: str | None


class ProductUnitConversionItem(BaseModel):
    id: str
    from_uom: UnitRef
    to_uom: UnitRef
    conversion_factor: str


class ProductListItem(BaseModel):
    id: str
    sku: str
    name: str
    hsn_code: str | None
    gst_rate: str | None
    base_uom: UnitRef
    supplier: SupplierRef | None = None
    cost_price: str
    selling_price: str
    mrp: str
    # Read-only, always 0 until the future Stock Ledger/Inventory module
    # writes to them (FR-STK-05/ASM-004) — never accepted as input here.
    reorder_level: str
    stock_qty_cache: str
    status: str
    created_at: str
    updated_at: str
    row_version: int


class ProductDetail(ProductListItem):
    unit_conversions: list[ProductUnitConversionItem] = []


class CreateProductRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    hsn_code: str | None = None
    gst_rate: Decimal = Field(decimal_places=2)
    base_uom_id: str
    supplier_id: str | None = None
    cost_price: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    selling_price: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    mrp: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)

    @field_validator("sku")
    @classmethod
    def _validate_sku(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not is_valid_sku(normalized):
            raise ValueError("SKU must be 1-50 uppercase letters, digits, hyphens or underscores")
        return normalized

    @field_validator("hsn_code")
    @classmethod
    def _validate_hsn(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_hsn(value):
            raise ValueError("HSN must be 4, 6 or 8 numeric digits")
        return value

    @field_validator("gst_rate")
    @classmethod
    def _validate_gst_rate(cls, value: Decimal) -> Decimal:
        return _validate_gst_rate(value)


class UpdateProductRequest(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hsn_code: str | None = None
    gst_rate: Decimal | None = Field(default=None, decimal_places=2)
    base_uom_id: str | None = None
    supplier_id: str | None = None
    cost_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    mrp: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    expected_row_version: int

    @field_validator("sku")
    @classmethod
    def _validate_sku(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().upper()
        if not is_valid_sku(normalized):
            raise ValueError("SKU must be 1-50 uppercase letters, digits, hyphens or underscores")
        return normalized

    @field_validator("hsn_code")
    @classmethod
    def _validate_hsn(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_hsn(value):
            raise ValueError("HSN must be 4, 6 or 8 numeric digits")
        return value

    @field_validator("gst_rate")
    @classmethod
    def _validate_gst_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _validate_gst_rate(value)

    # sku/name/base_uom_id/gst_rate are NOT NULL-backed (gst_rate is now
    # mandatory at the product-master level, see the module docstring) —
    # explicitly nulling any of them via PATCH would violate that, so reject
    # rather than letting a bad request surface as an opaque 500 at flush
    # time (same pattern as UpdateCustomerRequest/UpdateSupplierRequest).
    # supplier_id is NOT in this list — it's genuinely optional and clearing
    # it (removing a product's recorded supplier) is a valid operation.
    @model_validator(mode="after")
    def _reject_null_required_fields(self) -> "UpdateProductRequest":
        for required_field in ("sku", "name", "base_uom_id", "gst_rate"):
            if required_field in self.model_fields_set and getattr(self, required_field) is None:
                raise ValueError(f"{required_field} cannot be cleared")
        return self


class ActivateDeactivateProductRequest(BaseModel):
    expected_row_version: int


class CreateProductUnitConversionRequest(BaseModel):
    from_uom_id: str
    to_uom_id: str
    conversion_factor: Decimal = Field(gt=0, decimal_places=6)
