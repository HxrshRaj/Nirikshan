from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = "ok"


class TimeRange(BaseModel):
    minutes: int = Field(default=60, ge=1, le=60 * 24 * 14)
