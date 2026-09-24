"""Unit of Measure schemas (PROMPT-009).

A minimal read/create surface — no update/delete in this MVP (open
decision, see PROMPT-009-NOTES.md). Gated by products.view/products.create
rather than a dedicated permission family (see app/core/permissions.py).
"""

from pydantic import BaseModel, Field, field_validator


class UnitOfMeasureItem(BaseModel):
    id: str
    code: str
    name: str
    precision: int


class CreateUnitOfMeasureRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    precision: int = Field(default=2, ge=0, le=6)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        return value.strip().upper()
