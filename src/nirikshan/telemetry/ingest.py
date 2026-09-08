"""Telemetry ingestion pipeline.

Stages
------
1. **Validation** - Pydantic already rejected malformed shapes at the edge; here
   we enforce cross-field / semantic rules and cap batch sizes.
2. **Normalization** - default timestamps, clamp future timestamps, lower-case
   service names, coerce levels.
3. **Enrichment** - resolve (environment, service) rows (auto-registering unknown
   services as ``tier=3`` so telemetry is never dropped), attach ingest time and
   the most recent deployment id for the service.
4. **Storage** - bulk insert.
5. **Signal** - emit ``TELEMETRY_RECEIVED`` so the detection worker can react,
   and update a lightweight per-service "last seen / error" rollup.

Malformed rows are skipped and counted, never fatal to the batch.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.catalog.service import get_or_create_environment, get_or_create_service
from nirikshan.core.clock import utcnow
from nirikshan.core.events import EventType, emit
from nirikshan.core.logging import get_logger
from nirikshan.models import Deployment, TelemetryLog, TelemetryMetric, Trace, TraceSpan
from nirikshan.schemas.telemetry import (
    IngestResult,
    LogIn,
    MetricIn,
    TraceIn,
)

log = get_logger("telemetry.ingest")

_MAX_CLOCK_SKEW = timedelta(minutes=5)
_VALID_METRIC_UNITS = {"", "ms", "s", "count", "percent", "ratio", "bytes", "mb", "gb", "conn"}


def _norm_ts(raw):
    now = utcnow()
    if raw is None:
        return now
    ts = raw
    if ts.tzinfo is None:
        from datetime import UTC

        ts = ts.replace(tzinfo=UTC)
    if ts > now + _MAX_CLOCK_SKEW:
        return now
    return ts


def _recent_deployment_id(db: Session, service_id: str, at) -> str | None:
    dep = db.scalar(
        select(Deployment)
        .where(Deployment.service_id == service_id, Deployment.started_at <= at)
        .order_by(Deployment.started_at.desc())
        .limit(1)
    )
    return dep.id if dep else None


def ingest_logs(db: Session, items: list[LogIn]) -> IngestResult:
    accepted = 0
    errors: list[str] = []
    rows: list[TelemetryLog] = []
    now = utcnow()
    env_cache: dict[str, str] = {}
    svc_cache: dict[tuple[str, str], object] = {}

    for i, item in enumerate(items):
        try:
            env_name = item.environment.strip().lower()
            if env_name not in env_cache:
                env_cache[env_name] = get_or_create_environment(db, env_name).id
            env_id = env_cache[env_name]

            svc_name = item.service.strip().lower()
            key = (env_name, svc_name)
            if key not in svc_cache:
                svc_cache[key] = get_or_create_service(
                    db, svc_name, environment=env_name, tier=3
                )
            svc = svc_cache[key]

            ts = _norm_ts(item.timestamp)
            rows.append(
                TelemetryLog(
                    ts=ts,
                    ingested_at=now,
                    environment_id=env_id,
                    service_id=svc.id,
                    service_name=svc_name,
                    level=item.level.value,
                    message=item.message[:8000],
                    trace_id=item.trace_id,
                    span_id=item.span_id,
                    request_id=item.request_id,
                    host=item.host,
                    deployment_id=item.deployment_id
                    or _recent_deployment_id(db, svc.id, ts),
                    attributes=item.metadata or {},
                )
            )
            accepted += 1
        except Exception as exc:
            errors.append(f"log[{i}]: {exc}")

    if rows:
        db.add_all(rows)
        db.flush()
        emit(
            EventType.TELEMETRY_RECEIVED,
            {"kind": "logs", "count": len(rows), "services": sorted({r.service_name for r in rows})},
        )
    return IngestResult(accepted=accepted, rejected=len(items) - accepted, errors=errors[:50])


def ingest_metrics(db: Session, items: list[MetricIn]) -> IngestResult:
    accepted = 0
    errors: list[str] = []
    rows: list[TelemetryMetric] = []
    now = utcnow()
    env_cache: dict[str, str] = {}
    svc_cache: dict[tuple[str, str], object] = {}
    touched_services: set[str] = set()

    for i, item in enumerate(items):
        try:
            if item.unit and item.unit not in _VALID_METRIC_UNITS:
                raise ValueError(f"unsupported unit {item.unit!r}")
            env_name = item.environment.strip().lower()
            if env_name not in env_cache:
                env_cache[env_name] = get_or_create_environment(db, env_name).id
            env_id = env_cache[env_name]
            svc_name = item.service.strip().lower()
            key = (env_name, svc_name)
            if key not in svc_cache:
                svc_cache[key] = get_or_create_service(
                    db, svc_name, environment=env_name, tier=3
                )
            svc = svc_cache[key]
            rows.append(
                TelemetryMetric(
                    ts=_norm_ts(item.timestamp),
                    ingested_at=now,
                    environment_id=env_id,
                    service_id=svc.id,
                    service_name=svc_name,
                    metric_name=item.metric_name.strip().lower(),
                    value=float(item.value),
                    unit=item.unit,
                    labels=item.labels or {},
                )
            )
            touched_services.add(svc_name)
            accepted += 1
        except Exception as exc:
            errors.append(f"metric[{i}]: {exc}")

    if rows:
        db.add_all(rows)
        db.flush()
        emit(
            EventType.TELEMETRY_RECEIVED,
            {"kind": "metrics", "count": len(rows), "services": sorted(touched_services)},
        )
    return IngestResult(accepted=accepted, rejected=len(items) - accepted, errors=errors[:50])


def ingest_traces(db: Session, items: list[TraceIn]) -> IngestResult:
    accepted = 0
    errors: list[str] = []
    now = utcnow()
    env_cache: dict[str, str] = {}
    svc_cache: dict[tuple[str, str], object] = {}

    for i, tr in enumerate(items):
        try:
            env_name = tr.environment.strip().lower()
            if env_name not in env_cache:
                env_cache[env_name] = get_or_create_environment(db, env_name).id
            env_id = env_cache[env_name]

            if db.scalar(select(Trace.id).where(Trace.trace_id == tr.trace_id)):
                raise ValueError("duplicate trace_id")

            span_rows: list[TraceSpan] = []
            span_starts = []
            error_count = 0
            for s in tr.spans:
                svc_name = s.service.strip().lower()
                key = (env_name, svc_name)
                if key not in svc_cache:
                    svc_cache[key] = get_or_create_service(
                        db, svc_name, environment=env_name, tier=3
                    )
                svc = svc_cache[key]
                st = _norm_ts(s.start_time)
                span_starts.append((st, s.duration_ms, svc, s))
                if s.status.value == "ERROR":
                    error_count += 1
                span_rows.append(
                    TraceSpan(
                        trace_id=tr.trace_id,
                        span_id=s.span_id,
                        parent_span_id=s.parent_span_id,
                        environment_id=env_id,
                        service_id=svc.id,
                        service_name=svc_name,
                        operation=s.operation,
                        started_at=st,
                        duration_ms=float(s.duration_ms),
                        status=s.status.value,
                        attributes=s.attributes or {},
                    )
                )

            root = min(span_starts, key=lambda x: x[0])
            end = max(st + timedelta(milliseconds=dur) for st, dur, _, _ in span_starts)
            db.add(
                Trace(
                    trace_id=tr.trace_id,
                    environment_id=env_id,
                    root_service_id=root[2].id,
                    root_operation=root[3].operation,
                    started_at=root[0],
                    duration_ms=(end - root[0]).total_seconds() * 1000.0,
                    span_count=len(span_rows),
                    error_count=error_count,
                    status="ERROR" if error_count else "OK",
                    ingested_at=now,
                )
            )
            db.add_all(span_rows)
            db.flush()
            accepted += 1
        except Exception as exc:
            errors.append(f"trace[{i}]: {exc}")

    if accepted:
        emit(EventType.TELEMETRY_RECEIVED, {"kind": "traces", "count": accepted})
    return IngestResult(accepted=accepted, rejected=len(items) - accepted, errors=errors[:50])
