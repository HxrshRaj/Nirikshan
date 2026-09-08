"""Declarative base, a portable UTC datetime type, and common column mixins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nirikshan.core.ids import new_uuid


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend.

    PostgreSQL keeps ``timestamptz``; SQLite drops tzinfo on write, so on read we
    re-attach UTC. This means application code can always assume aware datetimes
    and never has to special-case the test database.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class UUIDPk:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
