"""Page[T] — standard paginated response for all list operations.

Cursor-based pagination. Supports iteration and len().
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard paginated response. Used by ALL list operations."""

    data: list[T]
    cursor: str | None = None
    has_more: bool = False
    total: int | None = None

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)
