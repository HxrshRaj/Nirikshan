"""Service-health rollups derived from raw telemetry.

These power the Overview dashboard and feed the alert-rule evaluator and the
investigator's ``get_service_health`` tool. Everything here is computed live
from stored telemetry - no numbers are fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nirikshan.catalog.service import find_service, list_services
from nirikshan.core.clock import utcnow
from nirikshan.domain.enums import ServiceHealth
from nirikshan.models import Service, TelemetryLog, TelemetryMetric

# Metric-name conventions the demo environment emits.
LATENCY_METRIC = "request_latency_ms"
REQUESTS_METRIC = "request_count"
ERRORS_METRIC = "error_count"
ERROR_RATE_METRIC = "error_rate"
CPU_METRIC = "cpu_usage"
MEM_METRIC = "memory_usage"
DB_CONN_METRIC = "database_connections"
QUEUE_METRIC = "queue_depth"


@dataclass
class ServiceHealthSnapshot:
    service: str
    service_id: str
    tier: int
    health: ServiceHealth
    window_seconds: int
    latency_p95_ms: float | None = None
    latency_avg_ms: float | None = None
    error_rate: float | None = None
    request_rate_per_min: float | None = None
    log_error_count: int = 0
    cpu_usage: float | None = None
    memory_usage: float | None = None
    db_connections: float | None = None
    queue_depth: float | None = None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["health"] = self.health.value
        return d


def _metric_stats(db: Session, service_id: str, name: str, since, until) -> list[float]:
    return list(
        db.scalars(
            select(TelemetryMetric.value).where(
                TelemetryMetric.service_id == service_id,
                TelemetryMetric.metric_name == name,
                TelemetryMetric.ts >= since,
                TelemetryMetric.ts <= until,
            )
        )
    )


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(int(round(0.95 * (len(s) - 1))), 0)
    return s[k]


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_service_health(
    db: Session, service: Service, *, window_seconds: int = 600
) -> ServiceHealthSnapshot:
    until = utcnow()
    since = until - timedelta(seconds=window_seconds)

    latency = _metric_stats(db, service.id, LATENCY_METRIC, since, until)
    req = _metric_stats(db, service.id, REQUESTS_METRIC, since, until)
    err = _metric_stats(db, service.id, ERRORS_METRIC, since, until)
    err_rate_direct = _metric_stats(db, service.id, ERROR_RATE_METRIC, since, until)
    cpu = _metric_stats(db, service.id, CPU_METRIC, since, until)
    mem = _metric_stats(db, service.id, MEM_METRIC, since, until)
    dbc = _metric_stats(db, service.id, DB_CONN_METRIC, since, until)
    queue = _metric_stats(db, service.id, QUEUE_METRIC, since, until)

    total_req = sum(req)
    total_err = sum(err)
    if err_rate_direct:
        error_rate = _avg(err_rate_direct)
    elif total_req > 0:
        error_rate = total_err / total_req
    else:
        error_rate = None

    log_errors = (
        db.scalar(
            select(func.count())
            .select_from(TelemetryLog)
            .where(
                TelemetryLog.service_id == service.id,
                TelemetryLog.ts >= since,
                TelemetryLog.level.in_(("ERROR", "FATAL")),
            )
        )
        or 0
    )

    snap = ServiceHealthSnapshot(
        service=service.name,
        service_id=service.id,
        tier=service.tier,
        health=ServiceHealth.HEALTHY,
        window_seconds=window_seconds,
        latency_p95_ms=_p95(latency),
        latency_avg_ms=_avg(latency),
        error_rate=error_rate,
        request_rate_per_min=(total_req / (window_seconds / 60)) if req else None,
        log_error_count=int(log_errors),
        cpu_usage=_avg(cpu),
        memory_usage=_avg(mem),
        db_connections=_avg(dbc),
        queue_depth=_avg(queue),
    )

    # --- classify ---
    degraded = False
    unhealthy = False
    if snap.latency_p95_ms is not None:
        if snap.latency_p95_ms > service.slo_latency_ms_p95 * 3:
            unhealthy = True
            snap.reasons.append(
                f"p95 latency {snap.latency_p95_ms:.0f}ms >> SLO {service.slo_latency_ms_p95:.0f}ms"
            )
        elif snap.latency_p95_ms > service.slo_latency_ms_p95:
            degraded = True
            snap.reasons.append(
                f"p95 latency {snap.latency_p95_ms:.0f}ms > SLO {service.slo_latency_ms_p95:.0f}ms"
            )
    if snap.error_rate is not None:
        if snap.error_rate > max(service.slo_error_rate * 5, 0.1):
            unhealthy = True
            snap.reasons.append(f"error rate {snap.error_rate:.1%} critical")
        elif snap.error_rate > service.slo_error_rate:
            degraded = True
            snap.reasons.append(f"error rate {snap.error_rate:.1%} > SLO {service.slo_error_rate:.1%}")
    if snap.log_error_count > 50:
        degraded = True
        snap.reasons.append(f"{snap.log_error_count} error logs in window")
    if req == [] and latency == [] and err_rate_direct == [] and log_errors == 0:
        snap.health = ServiceHealth.UNKNOWN
        snap.reasons.append("no telemetry in window")
        return snap

    snap.health = (
        ServiceHealth.UNHEALTHY
        if unhealthy
        else ServiceHealth.DEGRADED
        if degraded
        else ServiceHealth.HEALTHY
    )
    return snap


def refresh_all_health(db: Session, *, environment: str = "production") -> list[ServiceHealthSnapshot]:
    from nirikshan.catalog.service import set_service_health
    from nirikshan.core.errors import NotFoundError

    snaps: list[ServiceHealthSnapshot] = []
    try:
        services = list_services(db, environment=environment)
    except NotFoundError:
        return snaps  # topology not seeded yet - nothing to refresh
    for svc in services:
        snap = compute_service_health(db, svc)
        if snap.health != ServiceHealth.UNKNOWN:
            set_service_health(db, svc, snap.health)
        snaps.append(snap)
    return snaps


def health_for(db: Session, service_name: str, *, environment: str = "production") -> ServiceHealthSnapshot | None:
    svc = find_service(db, service_name.lower(), environment=environment)
    if svc is None:
        return None
    return compute_service_health(db, svc)
