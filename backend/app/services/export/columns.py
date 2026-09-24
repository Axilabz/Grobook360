"""Export column definitions — the ALLOWLIST every resource's Excel/PDF
export is built from (Global Export Framework, cross-cutting prompt).

Per-resource, explicit, hand-authored `ExportColumn` lists are the ONLY
thing that ever ends up in a generated file. A field existing on a
model/schema is never by itself sufficient for it to be exportable — it
must be added here first. This mirrors the SAME allowlist discipline
already used throughout this codebase for audit snapshots (never
`record.__dict__`) and API response schemas (never `**request.dict()`
blindly): internal fields (tenant_id, row_version, raw UUIDs, password
hashes, encrypted credential blobs) can never leak through this path
simply because they exist on the underlying ORM row.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal

ColumnType = Literal["text", "date", "datetime", "number", "currency", "percent", "boolean"]


@dataclass(frozen=True)
class ExportColumn:
    key: str
    header: str
    type: ColumnType
    # Extracts this column's value from one row object (whatever the
    # resource adapter's own row shape is — never the raw ORM instance,
    # see resources.py's own `to_row` per adapter).
    extractor: Callable[[Any], Any]
    width: int = 18  # Excel column width, characters


def field(key: str, header: str, col_type: ColumnType, width: int = 18) -> ExportColumn:
    """Shorthand for the common case: extractor = simple attribute/dict lookup."""

    def _extract(row: Any) -> Any:
        return row.get(key) if isinstance(row, dict) else getattr(row, key, None)

    return ExportColumn(key=key, header=header, type=col_type, extractor=_extract, width=width)


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None
