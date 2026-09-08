"""Read paths for telemetry: log search, metric series/aggregation, trace fetch."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from nirikshan.catalog.service import find_service, get_environment
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import NotFoundError
from nirikshan.domain.enums import LogLevel
from nirikshan.models import TelemetryLog, TelemetryMetric, Trace, TraceSpan
from nirikshan.schemas.telemetry import (
    LogOut,
    MetricPoint,
    MetricSeries,
    SpanOut,
    TraceOut,
)

_AGGS = {
    "avg": func.avg,
    "max": func.max,
    "min": func.min,
    "sum": func.sum,
    "count": func.count,
    "p95": None,  # handled in python
}


def _apply_time(stmt: Select, col, since: datetime, until: datetime) -> Select:
    return stmt.where(col >= since, col <= until)


def search_logs(
    db: Session,
    *,
    environment: str = "production",
    service: str | None = None,
    level: str | None = None,
    min_level: str | None = None,
    query: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    minutes: int = 60,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[LogOut], int]:
    until = until or utcnow()
    since = since or (until - timedelta(minutes=minutes))
    stmt = select(TelemetryLog)
    stmt = _apply_time(stmt, TelemetryLog.ts, since, until)

    try:
        env = get_environment(db, environment)
        stmt = stmt.where(TelemetryLog.environment_id == env.id)
    except NotFoundError:
        return [], 0

    if service:
        svc = find_service(db, service.lower(), environment=environment)
        if svc is None:
            return [], 0
        stmt = stmt.where(TelemetryLog.service_id == svc.id)
    if level:
        stmt = stmt.where(TelemetryLog.level == level.upper())
    if min_level:
        allowed = [lv.value for lv in LogLevel if lv.rank >= LogLevel(min_level.upper()).rank]
        stmt = stmt.where(TelemetryLog.level.in_(allowed))
    if trace_id:
        stmt = stmt.where(TelemetryLog.trace_id == trace_id)
    if request_id:
        stmt = stmt.where(TelemetryLog.request_id == request_id)
    if query:
        stmt = stmt.where(TelemetryLog.message.ilike(f"%{query}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(TelemetryLog.ts.desc()).limit(min(limit, 1000)).offset(offset)
    )
    out = [
        LogOut(
            id=r.id,
            ts=r.ts,
            service=r.service_name,
            environment_id=r.environment_id,
            level=r.level,
            message=r.message,
            trace_id=r.trace_id,
            span_id=r.span_id,
            request_id=r.request_id,
            host=r.host,
            attributes=r.attributes or {},
        )
        for r in rows
    ]
    return out, total


def log_histogram(
    db: Session,
    *,
    environment: str = "production",
    service: str | None = None,
    minutes: int = 60,
    buckets: int = 60,
) -> list[dict]:
    until = utcnow()
    since = until - timedelta(minutes=minutes)
    step = max((minutes * 60) // buckets, 1)
    rows = db.execute(
        _log_scope(db, environment, service, since, until).with_only_columns(
            TelemetryLog.ts, TelemetryLog.level
        )
    ).all()
    out: dict[int, dict[str, int]] = {}
    for ts, level in rows:
        idx = int((ts - since).total_seconds() // step)
        b = out.setdefault(idx, {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0, "FATAL": 0})
        b[level] = b.get(level, 0) + 1
    return [
        {"ts": (since + timedelta(seconds=i * step)).isoformat(), **out.get(i, {})}
        for i in range(buckets)
    ]


def _log_scope(db, environment, service, since, until) -> Select:
    stmt = _apply_time(select(TelemetryLog), TelemetryLog.ts, since, until)
    env = get_environment(db, environment)
    stmt = stmt.where(TelemetryLog.environment_id == env.id)
    if service:
        svc = find_service(db, service.lower(), environment=environment)
        stmt = stmt.where(TelemetryLog.service_id == (svc.id if svc else "none"))
    return stmt


def metric_series(
    db: Session,
    *,
    service: str,
    metric_name: str,
    environment: str = "production",
    minutes: int = 60,
    step_seconds: int = 60,
    aggregation: str = "avg",
    since: datetime | None = None,
    until: datetime | None = None,
) -> MetricSeries:
    if aggregation not in _AGGS:
        raise NotFoundError(f"unknown aggregation {aggregation!r}")
    until = until or utcnow()
    since = since or (until - timedelta(minutes=minutes))
    svc = find_service(db, service.lower(), environment=environment)
    if svc is None:
        return MetricSeries(
            service=service, metric_name=metric_name, unit="", points=[], aggregation=aggregation
        )
    rows: Sequence = db.execute(
        select(TelemetryMetric.ts, TelemetryMetric.value, TelemetryMetric.unit)
        .where(
            TelemetryMetric.service_id == svc.id,
            TelemetryMetric.metric_name == metric_name.lower(),
            TelemetryMetric.ts >= since,
            TelemetryMetric.ts <= until,
        )
        .order_by(TelemetryMetric.ts)
    ).all()
    unit = rows[0][2] if rows else ""
    buckets: dict[int, list[float]] = {}
    for ts, value, _unit in rows:
        idx = int((ts - since).total_seconds() // step_seconds)
        buckets.setdefault(idx, []).append(value)

    points: list[MetricPoint] = []
    for idx in sorted(buckets):
        vals = buckets[idx]
        points.append(
            MetricPoint(
                ts=since + timedelta(seconds=idx * step_seconds),
                value=_aggregate(vals, aggregation),
            )
        )
    return MetricSeries(
        service=service,
        metric_name=metric_name,
        unit=unit,
        points=points,
        aggregation=aggregation,
    )


def _aggregate(values: list[float], how: str) -> float:
    if not values:
        return 0.0
    if how == "avg":
        return sum(values) / len(values)
    if how == "max":
        return max(values)
    if how == "min":
        return min(values)
    if how == "sum":
        return sum(values)
    if how == "count":
        return float(len(values))
    if how == "p95":
        s = sorted(values)
        k = max(int(round(0.95 * (len(s) - 1))), 0)
        return s[k]
    return sum(values) / len(values)


def list_metric_names(db: Session, *, service: str | None = None) -> list[str]:
    stmt = select(TelemetryMetric.metric_name).distinct().order_by(TelemetryMetric.metric_name)
    if service:
        svc = find_service(db, service.lower())
        if svc is None:
            return []
        stmt = stmt.where(TelemetryMetric.service_id == svc.id)
    return list(db.scalars(stmt))


def get_trace(db: Session, trace_id: str) -> TraceOut:
    tr = db.scalar(select(Trace).where(Trace.trace_id == trace_id))
    if tr is None:
        raise NotFoundError(f"trace {trace_id!r} not found")
    spans = db.scalars(
        select(TraceSpan).where(TraceSpan.trace_id == trace_id).order_by(TraceSpan.started_at)
    )
    return TraceOut(
        trace_id=tr.trace_id,
        root_operation=tr.root_operation,
        started_at=tr.started_at,
        duration_ms=tr.duration_ms,
        span_count=tr.span_count,
        error_count=tr.error_count,
        status=tr.status,
        spans=[
            SpanOut(
                span_id=s.span_id,
                parent_span_id=s.parent_span_id,
                service=s.service_name,
                operation=s.operation,
                started_at=s.started_at,
                duration_ms=s.duration_ms,
                status=s.status,
                attributes=s.attributes or {},
            )
            for s in spans
        ],
    )


def list_traces(
    db: Session,
    *,
    environment: str = "production",
    service: str | None = None,
    only_errors: bool = False,
    minutes: int = 60,
    limit: int = 50,
) -> list[dict]:
    until = utcnow()
    since = until - timedelta(minutes=minutes)
    stmt = select(Trace).where(Trace.started_at >= since, Trace.started_at <= until)
    try:
        env = get_environment(db, environment)
        stmt = stmt.where(Trace.environment_id == env.id)
    except NotFoundError:
        return []
    if service:
        svc = find_service(db, service.lower(), environment=environment)
        if svc is None:
            return []
        stmt = stmt.where(Trace.root_service_id == svc.id)
    if only_errors:
        stmt = stmt.where(Trace.error_count > 0)
    rows = db.scalars(stmt.order_by(Trace.started_at.desc()).limit(limit))
    return [
        {
            "trace_id": r.trace_id,
            "root_operation": r.root_operation,
            "started_at": r.started_at.isoformat(),
            "duration_ms": r.duration_ms,
            "span_count": r.span_count,
            "error_count": r.error_count,
            "status": r.status,
        }
        for r in rows
    ]
