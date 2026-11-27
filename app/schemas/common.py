from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models built from ORM instances."""

    model_config = ConfigDict(from_attributes=True)


class StrictModel(BaseModel):
    """Base for request models: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class OkResponse(BaseModel):
    ok: bool = True
