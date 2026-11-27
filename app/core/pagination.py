"""Offset pagination helpers.

All list endpoints are paginated so a patient with a long history cannot force
an unbounded response. Page size is clamped to the configured maximum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    def meta(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "pages": self.pages,
        }


def clamp_page(page: int, page_size: int | None) -> tuple[int, int]:
    settings = get_settings()
    safe_page = max(1, page)
    safe_size = page_size or settings.default_page_size
    safe_size = max(1, min(safe_size, settings.max_page_size))
    return safe_page, safe_size


def paginate(db: Session, stmt: Select[Any], *, page: int, page_size: int | None) -> Page[Any]:
    safe_page, safe_size = clamp_page(page, page_size)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(
        db.scalars(stmt.limit(safe_size).offset((safe_page - 1) * safe_size))
    )
    return Page(items=items, total=int(total), page=safe_page, page_size=safe_size)
