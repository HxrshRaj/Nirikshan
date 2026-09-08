"""Telemetry storage: logs, metrics, traces and spans.

Indexing follows the dominant read patterns:
* logs   -> (service, ts), (trace_id), (level, ts)
* metrics-> (service, metric_name, ts)
* spans  -> (trace_id), (service, ts)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nirikshan.models.base import Base, UTCDateTime, UUIDPk


class TelemetryLog(UUIDPk, Base):
    __tablename__ = "telemetry_logs"
    __table_args__ = (
        Index("ix_logs_service_ts", "service_id", "ts"),
        Index("ix_logs_level_ts", "level", "ts"),
        Index("ix_logs_trace", "trace_id"),
        Index("ix_logs_env_ts", "environment_id", "ts"),
    )

    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    span_id: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(64))
    host: Mapped[str | None] = mapped_column(String(200))
    deployment_id: Mapped[str | None] = mapped_column(String(36))
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class TelemetryMetric(UUIDPk, Base):
    __tablename__ = "telemetry_metrics"
    __table_args__ = (
        Index("ix_metrics_lookup", "service_id", "metric_name", "ts"),
        Index("ix_metrics_name_ts", "metric_name", "ts"),
    )

    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="")
    labels: Mapped[dict] = mapped_column(JSON, default=dict)


class Trace(UUIDPk, Base):
    __tablename__ = "telemetry_traces"
    __table_args__ = (Index("ix_traces_root_ts", "root_service_id", "started_at"),)

    trace_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    root_service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id"))
    root_operation: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    span_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(8), default="OK")
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class TraceSpan(UUIDPk, Base):
    __tablename__ = "trace_spans"
    __table_args__ = (
        Index("ix_spans_trace", "trace_id"),
        Index("ix_spans_service_ts", "service_id", "started_at"),
    )

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    span_id: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(32))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(8), default="OK")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
