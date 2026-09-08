"""Deployment tracking - a first-class evidence source for investigations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nirikshan.domain.enums import DeploymentStatus
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class Deployment(UUIDPk, Timestamps, Base):
    __tablename__ = "deployments"
    __table_args__ = (Index("ix_deploy_service_started", "service_id", "started_at"),)

    ref: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(60), nullable=False)
    previous_version: Mapped[str | None] = mapped_column(String(60))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    change_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(
        String(16), default=DeploymentStatus.SUCCEEDED.value, nullable=False
    )
    triggered_by: Mapped[str] = mapped_column(String(120), default="ci")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
