"""Incident memory / RAG store.

Every resolved incident is distilled into a ``HistoricalIncident`` record with an
embedding vector so the investigator can retrieve semantically similar past
incidents as supporting context.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class HistoricalIncident(UUIDPk, Timestamps, Base):
    __tablename__ = "historical_incidents"
    __table_args__ = (Index("ix_hist_service", "service_name"),)

    incident_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    incident_ref: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="SEV-3")
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_minutes: Mapped[float] = mapped_column(Float, default=0.0)

    summary: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    affected_services: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    # Embedding for semantic retrieval (provider-abstracted; local hash fallback).
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    embedding_model: Mapped[str] = mapped_column(String(60), default="")
    doc_text: Mapped[str] = mapped_column(Text, default="")
