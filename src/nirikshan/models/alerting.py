"""Alert rules, alerts, anomalies and metric baselines."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nirikshan.domain.enums import AlertSeverity, AlertState
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class AlertRule(UUIDPk, Timestamps, Base):
    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id"), index=True)
    signal_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # e.g. metric_name for METRIC/RESOURCE, or a substring for LOG_MATCH
    subject: Mapped[str] = mapped_column(String(120), default="")
    comparison: Mapped[str] = mapped_column(String(4), default="gt")
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    for_seconds: Mapped[int] = mapped_column(Integer, default=300)
    window_seconds: Mapped[int] = mapped_column(Integer, default=300)
    severity: Mapped[str] = mapped_column(String(10), default=AlertSeverity.HIGH.value)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    # runtime evaluation state
    breaching_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active_alert_id: Mapped[str | None] = mapped_column(String(36))


class Alert(UUIDPk, Timestamps, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_state_service", "state", "service_id"),
        Index("ix_alerts_fired_at", "fired_at"),
    )

    ref: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("alert_rules.id"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    signal_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    subject: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[str] = mapped_column(String(10), default=AlertSeverity.HIGH.value)
    state: Mapped[str] = mapped_column(String(12), default=AlertState.FIRING.value, nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    fired_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    anomaly_id: Mapped[str | None] = mapped_column(ForeignKey("anomalies.id"))
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class Anomaly(UUIDPk, Base):
    __tablename__ = "anomalies"
    __table_args__ = (Index("ix_anomaly_service_metric_ts", "service_id", "metric_name", "detected_at"),)

    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_low: Mapped[float] = mapped_column(Float, nullable=False)
    expected_high: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), default="high")  # high|low
    window_seconds: Mapped[int] = mapped_column(Integer, default=900)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricBaseline(UUIDPk, Timestamps, Base):
    __tablename__ = "metric_baselines"
    __table_args__ = (
        Index("ix_baseline_key", "service_id", "metric_name", unique=True),
    )

    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    mean: Mapped[float] = mapped_column(Float, default=0.0)
    std: Mapped[float] = mapped_column(Float, default=0.0)
    ewma: Mapped[float] = mapped_column(Float, default=0.0)
    ewvar: Mapped[float] = mapped_column(Float, default=0.0)
    p50: Mapped[float] = mapped_column(Float, default=0.0)
    p95: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_from_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)
