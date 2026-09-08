"""Telemetry retention enforcement (demo-safe; run periodically by the worker)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.config import get_settings
from nirikshan.core.logging import get_logger
from nirikshan.models import TelemetryLog, TelemetryMetric, Trace, TraceSpan

log = get_logger("telemetry.retention")


def enforce_retention(db: Session) -> dict[str, int]:
    s = get_settings()
    now = utcnow()
    deleted: dict[str, int] = {}

    log_cut = now - timedelta(hours=s.retention_logs_hours)
    deleted["logs"] = db.execute(
        delete(TelemetryLog).where(TelemetryLog.ts < log_cut)
    ).rowcount or 0

    metric_cut = now - timedelta(hours=s.retention_metrics_hours)
    deleted["metrics"] = db.execute(
        delete(TelemetryMetric).where(TelemetryMetric.ts < metric_cut)
    ).rowcount or 0

    trace_cut = now - timedelta(hours=s.retention_traces_hours)
    old_traces = list(
        db.execute(Trace.__table__.select().where(Trace.started_at < trace_cut)).fetchall()
    )
    trace_ids = [t.trace_id for t in old_traces]
    if trace_ids:
        db.execute(delete(TraceSpan).where(TraceSpan.trace_id.in_(trace_ids)))
        db.execute(delete(Trace).where(Trace.trace_id.in_(trace_ids)))
    deleted["traces"] = len(trace_ids)

    if any(deleted.values()):
        log.info("retention.enforced", **deleted)
    return deleted
