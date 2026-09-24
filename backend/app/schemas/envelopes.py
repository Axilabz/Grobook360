"""Standard API response envelopes (API Contract Specification v1.0 S6)."""

from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    correlation_id: UUID
    timestamp: str | None = None


class SuccessResponse(BaseModel, Generic[T]):
    data: T
    meta: Meta


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    pagination: Pagination
    meta: Meta


class ErrorDetail(BaseModel):
    field: str | None = None
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail | dict[str, Any]] = []


class ErrorResponse(BaseModel):
    error: ErrorBody
    meta: Meta
