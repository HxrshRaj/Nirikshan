"""Incident aggregate: incident, timeline events, evidence, hypotheses."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nirikshan.domain.enums import IncidentStatus, Severity
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class Incident(UUIDPk, Timestamps, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incident_status_sev", "status", "severity"),
        Index("ix_incident_service_detected", "service_id", "detected_at"),
        Index("ix_incident_dedup", "dedup_key"),
    )

    ref: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default=Severity.SEV3.value, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=IncidentStatus.DETECTED.value, nullable=False
    )
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)

    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    mitigated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    summary: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float)
    contributing_factors: Mapped[list] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)
    affected_services: Mapped[list] = mapped_column(JSON, default=list)
    blast_radius: Mapped[dict] = mapped_column(JSON, default=dict)

    dedup_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    correlated_alert_refs: Mapped[list] = mapped_column(JSON, default=list)

    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    resolved_by: Mapped[str | None] = mapped_column(String(120))
    last_investigation_run_id: Mapped[str | None] = mapped_column(String(36))

    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentEvent.at"
    )
    evidence: Mapped[list[IncidentEvidence]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list[IncidentHypothesis]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentHypothesis.rank",
    )


class IncidentEvent(UUIDPk, Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_at", "incident_id", "at"),)

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    source: Mapped[str] = mapped_column(String(48), default="system")  # system|ai|human
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    incident: Mapped[Incident] = relationship(back_populates="events")


class IncidentEvidence(UUIDPk, Base):
    __tablename__ = "incident_evidence"
    __table_args__ = (Index("ix_evidence_incident_kind", "incident_id", "kind"),)

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(40), default="")
    ref_id: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    collected_by: Mapped[str] = mapped_column(String(48), default="investigator")
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    incident: Mapped[Incident] = relationship(back_populates="evidence")


class IncidentHypothesis(UUIDPk, Base):
    __tablename__ = "incident_hypotheses"
    __table_args__ = (Index("ix_hypo_incident_rank", "incident_id", "rank"),)

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_selected: Mapped[bool] = mapped_column(default=False)

    incident: Mapped[Incident] = relationship(back_populates="hypotheses")
