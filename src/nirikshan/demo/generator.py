"""Deterministic telemetry generator for the demo environment.

Given the standard topology and an optional fault scenario, it writes a coherent
window of metrics, logs and traces. Everything is seeded so runs are
reproducible (spec 88). If a remediation has suppressed the scenario's fault on
a service (via ``Service.attributes['suppressed_faults']``), the generator ramps
that service back to baseline - which is what lets remediation verification
observe a real recovery (spec 33, 93).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dateutil.parser import isoparse
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.ids import short_token
from nirikshan.demo.topology import BASELINE, ensure_topology
from nirikshan.models import (
    Deployment,
    Service,
    TelemetryLog,
    TelemetryMetric,
    Trace,
    TraceSpan,
)

SEED = 20260907


@dataclass
class FaultSpec:
    """Multiplicative effect of a fault on a service's metrics over the window."""

    service: str
    category: str
    metric_multipliers: dict[str, float]
    add_error_rate: float = 0.0
    error_log_message: str = ""
    error_logs_per_min: int = 0
    deployment: dict | None = None
    mark_datastore_unhealthy: bool = False


@dataclass
class ScenarioSpec:
    key: str
    title: str
    description: str
    faults: list[FaultSpec] = field(default_factory=list)
    expected_category: str = "inconclusive"
    expected_service: str = ""
    expected_evidence: list[str] = field(default_factory=list)


def _diurnal(ts: datetime) -> float:
    # gentle daily ripple, +/-12%
    frac = (ts.hour * 3600 + ts.minute * 60) / 86400.0
    return 1.0 + 0.12 * math.sin(2 * math.pi * frac)


def _suppressed_at(svc: Service, categories: set[str]) -> datetime | None:
    attrs = svc.attributes or {}
    if not (set(attrs.get("suppressed_faults", [])) & categories):
        return None
    ts = attrs.get("runtime_updated_at")
    try:
        return isoparse(ts) if ts else None
    except (ValueError, TypeError):
        return None


def _fault_scale(
    ts: datetime, fault_start: datetime, recover_at: datetime | None, ramp_minutes: float = 5.0
) -> float:
    """0..1 intensity of the fault at time ``ts``."""
    if ts < fault_start:
        return 0.0
    ramp_up = min((ts - fault_start).total_seconds() / (ramp_minutes * 60), 1.0)
    if recover_at and ts >= recover_at:
        # remediation applied -> fault clears over ~2 minutes
        healed = min((ts - recover_at).total_seconds() / 120.0, 1.0)
        return max(0.0, ramp_up * (1.0 - healed))
    return ramp_up


def generate(
    db: Session,
    *,
    minutes_history: int = 180,
    step_seconds: int = 60,
    scenario: ScenarioSpec | None = None,
    fault_minutes: int = 18,
    now: datetime | None = None,
    reset_window: bool = True,
) -> dict:
    services = {s.name: s for s in ensure_topology(db)}
    rng = random.Random(SEED + (hash(scenario.key) & 0xFFFF if scenario else 0))
    now = now or utcnow()
    start = now - timedelta(minutes=minutes_history)
    fault_start = now - timedelta(minutes=fault_minutes)

    faults_by_service: dict[str, FaultSpec] = {f.service: f for f in (scenario.faults if scenario else [])}

    if reset_window:
        _purge_window(db, start - timedelta(minutes=5), now + timedelta(minutes=1), list(services.values()))

    # deployments referenced by the scenario
    for f in faults_by_service.values():
        if f.deployment:
            _insert_deployment(db, services[f.service], f.deployment, fault_start)

    metric_rows: list[TelemetryMetric] = []
    log_rows: list[TelemetryLog] = []
    steps = int(minutes_history * 60 / step_seconds)

    for name, svc in services.items():
        base = BASELINE.get(name, {})
        fault = faults_by_service.get(name)
        recover_at = _suppressed_at(svc, {fault.category} if fault else set()) if fault else None
        for i in range(steps + 1):
            ts = start + timedelta(seconds=i * step_seconds)
            if ts > now:
                break
            dfac = _diurnal(ts)
            scale = _fault_scale(ts, fault_start, recover_at) if fault else 0.0
            req = None
            err_rate = None
            for metric, bval in base.items():
                noise = 1.0 + rng.uniform(-0.06, 0.06)
                val = bval * dfac * noise
                if fault and metric in fault.metric_multipliers:
                    mult = fault.metric_multipliers[metric]
                    val *= 1.0 + (mult - 1.0) * scale
                if metric == "error_rate":
                    val += fault.add_error_rate * scale if fault else 0.0
                    val = max(0.0, min(val, 0.95))
                    err_rate = val
                if metric == "request_count":
                    req = max(1.0, val)
                metric_rows.append(_metric(svc, metric, val, ts, now))
            # derived error_count from rate * requests
            if req is not None and err_rate is not None:
                metric_rows.append(_metric(svc, "error_count", round(req * err_rate, 2), ts, now))

            # baseline low-rate logs
            if rng.random() < 0.25:
                log_rows.append(_log(svc, "INFO", _info_line(rng, name), ts, now))
            if rng.random() < 0.08:
                log_rows.append(_log(svc, "WARN", "elevated GC pause observed", ts, now))
            # fault error logs
            if fault and scale > 0.15 and fault.error_logs_per_min:
                for _ in range(max(1, int(fault.error_logs_per_min * scale))):
                    log_rows.append(
                        _log(svc, "ERROR", fault.error_log_message, ts, now,
                             trace_id="trc_" + short_token(12).lower())
                    )
            elif err_rate and req and rng.random() < min(err_rate * 4, 0.5):
                log_rows.append(_log(svc, "ERROR", "request failed: downstream 5xx", ts, now))

    db.add_all(metric_rows)
    db.add_all(log_rows)
    db.flush()

    trace_count = _emit_traces(db, services, faults_by_service, fault_start, now, rng)

    return {
        "scenario": scenario.key if scenario else "normal",
        "services": len(services),
        "metric_points": len(metric_rows),
        "log_lines": len(log_rows),
        "traces": trace_count,
        "window": {"start": start.isoformat(), "now": now.isoformat(), "fault_start": fault_start.isoformat()},
    }


# --------------------------------------------------------------------------- #
def _metric(svc: Service, name: str, value: float, ts: datetime, now: datetime) -> TelemetryMetric:
    unit = {"request_latency_ms": "ms", "error_rate": "ratio", "cpu_usage": "ratio",
            "memory_usage": "ratio"}.get(name, "count")
    return TelemetryMetric(
        ts=ts, ingested_at=now, environment_id=svc.environment_id, service_id=svc.id,
        service_name=svc.name, metric_name=name, value=round(float(value), 4), unit=unit, labels={},
    )


def _log(svc: Service, level: str, msg: str, ts: datetime, now: datetime, *, trace_id: str | None = None) -> TelemetryLog:
    return TelemetryLog(
        ts=ts, ingested_at=now, environment_id=svc.environment_id, service_id=svc.id,
        service_name=svc.name, level=level, message=msg, trace_id=trace_id,
        host=f"{svc.name}-{short_token(4).lower()}", attributes={},
    )


_INFO_LINES = [
    "handled request", "cache hit", "healthcheck ok", "processed batch",
    "connection established", "request completed 200",
]


def _info_line(rng: random.Random, service: str) -> str:
    return f"{service}: {rng.choice(_INFO_LINES)}"


def _insert_deployment(db: Session, svc: Service, spec: dict, fault_start: datetime) -> Deployment:
    offset = spec.get("minutes_before_fault", 8)
    started = fault_start - timedelta(minutes=offset)
    exists = db.scalar(
        select(Deployment).where(
            Deployment.service_id == svc.id, Deployment.version == spec["version"],
            Deployment.started_at >= started - timedelta(minutes=1),
        )
    )
    if exists:
        return exists
    dep = Deployment(
        ref="DEP-" + short_token(6),
        environment_id=svc.environment_id, service_id=svc.id, service_name=svc.name,
        version=spec["version"], previous_version=spec.get("previous_version", "prev"),
        commit_sha=short_token(10).lower(), change_summary=spec.get("change_summary", ""),
        started_at=started, completed_at=started + timedelta(minutes=2),
        status="SUCCEEDED", triggered_by="ci",
    )
    db.add(dep)
    db.flush()
    return dep


def _emit_traces(db, services, faults, fault_start, now, rng) -> int:
    gw = services.get("api-gateway")
    order = services.get("order-service")
    pay = services.get("payment-service")
    if not (gw and order and pay):
        return 0
    count = 0
    for _k in range(24):
        ts = now - timedelta(seconds=rng.randint(30, 55 * 60))
        is_fault = ts >= fault_start and any(
            f.service in ("payment-service", "order-service") for f in faults.values()
        )
        tid = "trc_" + short_token(14).lower()
        base_ms = rng.uniform(60, 160)
        pay_ms = base_ms + (rng.uniform(500, 900) if is_fault else rng.uniform(20, 90))
        spans = [
            TraceSpan(trace_id=tid, span_id=short_token(8).lower(), parent_span_id=None,
                      environment_id=gw.environment_id, service_id=gw.id, service_name=gw.name,
                      operation="POST /checkout", started_at=ts, duration_ms=pay_ms + base_ms,
                      status="OK", attributes={"http.route": "/checkout"}),
            TraceSpan(trace_id=tid, span_id=short_token(8).lower(), parent_span_id=None,
                      environment_id=order.environment_id, service_id=order.id, service_name=order.name,
                      operation="OrderService.place", started_at=ts + timedelta(milliseconds=5),
                      duration_ms=pay_ms + 20, status="OK", attributes={}),
            TraceSpan(trace_id=tid, span_id=short_token(8).lower(), parent_span_id=None,
                      environment_id=pay.environment_id, service_id=pay.id, service_name=pay.name,
                      operation="PaymentService.charge", started_at=ts + timedelta(milliseconds=12),
                      duration_ms=pay_ms, status="ERROR" if is_fault else "OK",
                      attributes={"db.statement": "SELECT ... FROM payments", "error": is_fault}),
        ]
        db.add_all(spans)
        db.add(Trace(
            trace_id=tid, environment_id=gw.environment_id, root_service_id=gw.id,
            root_operation="POST /checkout", started_at=ts, duration_ms=pay_ms + base_ms,
            span_count=len(spans), error_count=1 if is_fault else 0,
            status="ERROR" if is_fault else "OK", ingested_at=now,
        ))
        count += 1
    db.flush()
    return count


def _purge_window(db: Session, start, end, services: list[Service]) -> None:
    from sqlalchemy import delete

    ids = [s.id for s in services]
    db.execute(delete(TelemetryMetric).where(TelemetryMetric.service_id.in_(ids),
                                             TelemetryMetric.ts >= start, TelemetryMetric.ts <= end))
    db.execute(delete(TelemetryLog).where(TelemetryLog.service_id.in_(ids),
                                          TelemetryLog.ts >= start, TelemetryLog.ts <= end))
    tids = [
        t.trace_id for t in db.execute(
            select(Trace.trace_id).where(Trace.started_at >= start, Trace.started_at <= end)
        ).all()
    ]
    if tids:
        db.execute(delete(TraceSpan).where(TraceSpan.trace_id.in_(tids)))
        db.execute(delete(Trace).where(Trace.trace_id.in_(tids)))
    db.flush()
