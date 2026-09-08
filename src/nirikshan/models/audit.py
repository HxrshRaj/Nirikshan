"""Immutable audit log for sensitive actions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nirikshan.models.base import Base, UTCDateTime, UUIDPk


class AuditLog(UUIDPk, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_at", "at"),
    )

    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)  # email or "system"/"ai:..."
    actor_role: Mapped[str] = mapped_column(String(24), default="")
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(48), default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="")
    result: Mapped[str] = mapped_column(String(16), default="success")
    ip: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
