"""Optimistic concurrency helper (PROMPT-001 S11 / API Contract S10.2).

Mutable updates must supply the row_version they last read. A mismatch never
silently overwrites — it raises ConcurrencyConflictError, which the error handler
maps to HTTP 412 with the current row_version so the caller can refresh/merge.
"""

from typing import Any

from app.core.exceptions import ConcurrencyConflictError


def check_row_version(entity: Any, expected_row_version: int) -> None:
    if entity.row_version != expected_row_version:
        raise ConcurrencyConflictError(
            "Row version mismatch: the record has been modified since it was read",
            details=[
                {
                    "field": "row_version",
                    "code": "CONCURRENCY_CONFLICT",
                    "message": f"expected={expected_row_version} current={entity.row_version}",
                }
            ],
        )


def apply_mutable_update(entity: Any) -> None:
    """Call after mutating a tracked entity's fields, before commit."""
    entity.row_version += 1
