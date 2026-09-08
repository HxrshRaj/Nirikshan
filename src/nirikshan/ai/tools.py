"""Structured, permission-bounded evidence tools for the investigator agent.

Why tools instead of handing the model the database (spec 24, 102):

* every access is an explicit, named, logged call with typed arguments
* the model only ever sees curated, provenance-tagged results - never raw rows,
  connection strings, other tenants' data, or secrets
* each tool is individually rate-limitable and auditable
* the same tools power deterministic evidence collection in tests and eval

Each call is recorded as an ``AgentToolCall`` row (sequence, args, result
summary, row count, duration, ok/error).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nirikshan.catalog.graph import load_graph
from nirikshan.catalog.service import find_service
from nirikshan.core.clock import utcnow
from nirikshan.core.logging import get_logger
from nirikshan.detection.baseline import load_baseline, recompute_baseline
from nirikshan.models import (
    AgentToolCall,
    Alert,
    Anomaly,
    Deployment,
    Incident,
    TelemetryLog,
)
from nirikshan.telemetry.aggregate import compute_service_health
from nirikshan.telemetry.query import get_trace, list_traces, metric_series

log = get_logger("ai.tools")


@dataclass
class ToolContext:
    db: Session
    incident: Incident
    run_id: str
    environment_id: str
    _seq: int = 0
    calls: list[AgentToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]


# --------------------------------------------------------------------------- #
# Individual tools
# --------------------------------------------------------------------------- #
def _t_query_metrics(ctx: ToolContext, *, service: str, metric: str, minutes: int = 30) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    series = metric_series(
        ctx.db, service=service.lower(), metric_name=metric.lower(), minutes=minutes, step_seconds=60
    )
    values = [p.value for p in series.points]
    baseline = load_baseline(ctx.db, svc.id, metric.lower()) or recompute_baseline(
        ctx.db, svc, metric.lower()
    )
    current = values[-1] if values else None
    zscore = None
    if baseline and current is not None:
        spread = max(baseline.std, baseline.ewstd, 1e-9)
        zscore = round((current - baseline.mean) / spread, 2)
    anomaly = ctx.db.scalar(
        select(Anomaly)
        .where(
            Anomaly.service_id == svc.id,
            Anomaly.metric_name == metric.lower(),
            Anomaly.detected_at >= utcnow() - timedelta(minutes=minutes),
        )
        .order_by(Anomaly.detected_at.desc())
    )
    return {
        "service": service.lower(),
        "metric": metric.lower(),
        "unit": series.unit,
        "current": round(current, 3) if current is not None else None,
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
        "baseline_mean": round(baseline.mean, 3) if baseline else None,
        "baseline_std": round(max(baseline.std, baseline.ewstd), 3) if baseline else None,
        "baseline_p95": round(baseline.p95, 3) if baseline else None,
        "zscore": zscore,
        "anomaly": bool(anomaly),
        "anomaly_score": round(anomaly.score, 2) if anomaly else None,
        "anomaly_direction": anomaly.direction if anomaly else None,
        "points": [{"ts": p.ts.isoformat(), "value": round(p.value, 3)} for p in series.points[-30:]],
        "rows": len(values),
    }


_ERROR_PATTERN_KEYWORDS = [
    "connection pool", "acquire connection", "too many clients", "timeout acquiring",
    "pool exhausted", "connection refused", "deadline exceeded", "circuit open",
    "5xx", "nullpointer", "unhandled exception", "OOM", "out of memory",
]


def _t_search_logs(
    ctx: ToolContext, *, service: str, query: str = "", level: str = "ERROR", minutes: int = 30, limit: int = 20
) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    since = utcnow() - timedelta(minutes=minutes)
    stmt = select(TelemetryLog).where(
        TelemetryLog.service_id == svc.id, TelemetryLog.ts >= since
    )
    if level:
        from nirikshan.domain.enums import LogLevel

        allowed = [lv.value for lv in LogLevel if lv.rank >= LogLevel(level.upper()).rank]
        stmt = stmt.where(TelemetryLog.level.in_(allowed))
    if query:
        stmt = stmt.where(TelemetryLog.message.ilike(f"%{query}%"))
    rows = list(ctx.db.scalars(stmt.order_by(TelemetryLog.ts.desc()).limit(limit)))

    total_err = ctx.db.scalar(
        select(func.count()).select_from(TelemetryLog).where(
            TelemetryLog.service_id == svc.id,
            TelemetryLog.ts >= since,
            TelemetryLog.level.in_(("ERROR", "FATAL")),
        )
    ) or 0
    total_fatal = ctx.db.scalar(
        select(func.count()).select_from(TelemetryLog).where(
            TelemetryLog.service_id == svc.id, TelemetryLog.ts >= since, TelemetryLog.level == "FATAL"
        )
    ) or 0

    sample_text = " ".join(r.message for r in rows).lower()
    patterns = [kw for kw in _ERROR_PATTERN_KEYWORDS if kw in sample_text]
    return {
        "service": service.lower(),
        "error_count": int(total_err),
        "fatal_count": int(total_fatal),
        "top_patterns": patterns,
        "top_patterns_text": "; ".join(patterns),
        "sample": [
            {"ts": r.ts.isoformat(), "level": r.level, "message": r.message[:280], "trace_id": r.trace_id}
            for r in rows
        ],
        "rows": len(rows),
    }


def _t_get_service_health(ctx: ToolContext, *, service: str) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    snap = compute_service_health(ctx.db, svc)
    d = snap.as_dict()
    d["rows"] = 1
    return d


def _t_get_recent_deployments(ctx: ToolContext, *, service: str, minutes: int = 180) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    since = utcnow() - timedelta(minutes=minutes)
    rows = list(
        ctx.db.scalars(
            select(Deployment)
            .where(Deployment.service_id == svc.id, Deployment.started_at >= since)
            .order_by(Deployment.started_at.desc())
        )
    )
    detected = ctx.incident.detected_at
    out = []
    for d in rows:
        mins_before = round((detected - (d.completed_at or d.started_at)).total_seconds() / 60.0, 1)
        out.append(
            {
                "ref": d.ref,
                "service": d.service_name,
                "version": d.version,
                "previous_version": d.previous_version,
                "commit_sha": d.commit_sha,
                "change_summary": d.change_summary,
                "started_at": d.started_at.isoformat(),
                "status": d.status,
                "minutes_before_incident": mins_before,
            }
        )
    return {"service": service.lower(), "deployments": out, "rows": len(out)}


def _t_get_dependencies(ctx: ToolContext, *, service: str) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    g = load_graph(ctx.db, svc.environment_id)
    depends_on = [g.name(x) for x in g.depends_on.get(svc.id, set())]
    dependents = [g.name(x) for x in g.dependents.get(svc.id, set())]
    unhealthy = []
    for dep_id in g.depends_on.get(svc.id, set()):
        dep_svc = g.services.get(dep_id)
        if not dep_svc:
            continue
        snap = compute_service_health(ctx.db, dep_svc)
        if snap.health.value in ("DEGRADED", "UNHEALTHY"):
            unhealthy.append(
                {
                    "service": dep_svc.name,
                    "kind": dep_svc.kind,
                    "health": snap.health.value,
                    "reasons": snap.reasons,
                }
            )
    return {
        "service": service.lower(),
        "depends_on": sorted(depends_on),
        "dependents": sorted(dependents),
        "unhealthy_dependencies": unhealthy,
        "blast_radius": g.blast_radius(svc.id),
        "rows": len(depends_on) + len(dependents),
    }


def _t_get_alert_history(ctx: ToolContext, *, service: str, minutes: int = 120) -> dict:
    svc = find_service(ctx.db, service.lower())
    if svc is None:
        return {"error": f"unknown service {service!r}", "rows": 0}
    since = utcnow() - timedelta(minutes=minutes)
    rows = list(
        ctx.db.scalars(
            select(Alert)
            .where(Alert.service_id == svc.id, Alert.fired_at >= since)
            .order_by(Alert.fired_at.desc())
        )
    )
    return {
        "service": service.lower(),
        "alerts": [
            {
                "ref": a.ref,
                "title": a.title,
                "signal_kind": a.signal_kind,
                "subject": a.subject,
                "severity": a.severity,
                "state": a.state,
                "observed_value": a.observed_value,
                "threshold": a.threshold,
                "fired_at": a.fired_at.isoformat(),
            }
            for a in rows
        ],
        "rows": len(rows),
    }


def _t_get_error_traces(ctx: ToolContext, *, service: str, minutes: int = 30) -> dict:
    traces = list_traces(
        ctx.db, service=service.lower(), only_errors=True, minutes=minutes, limit=5
    )
    detail = None
    if traces:
        try:
            t = get_trace(ctx.db, traces[0]["trace_id"])
            failing = next((s for s in t.spans if s.status == "ERROR"), None)
            detail = {
                "trace_id": t.trace_id,
                "root_operation": t.root_operation,
                "duration_ms": t.duration_ms,
                "failing_span": (
                    {"service": failing.service, "operation": failing.operation,
                     "duration_ms": failing.duration_ms, "attributes": failing.attributes}
                    if failing
                    else None
                ),
                "span_count": t.span_count,
            }
        except Exception:
            detail = None
    return {"service": service.lower(), "error_traces": traces, "example": detail, "rows": len(traces)}


def _t_get_related_incidents(ctx: ToolContext, *, query: str, k: int = 3) -> dict:
    from nirikshan.incidents.memory import similar_incidents

    results = similar_incidents(
        ctx.db, query_text=query, exclude_incident_id=ctx.incident.id, k=k
    )
    return {"query": query[:200], "results": results, "rows": len(results)}


def _t_get_resource_usage(ctx: ToolContext, *, service: str, minutes: int = 30) -> dict:
    out = {}
    for m in ("cpu_usage", "memory_usage", "database_connections", "queue_depth"):
        r = _t_query_metrics(ctx, service=service, metric=m, minutes=minutes)
        if r.get("rows"):
            out[m] = {"current": r["current"], "baseline_mean": r["baseline_mean"], "anomaly": r["anomaly"]}
    return {"service": service.lower(), "resources": out, "rows": len(out)}


# --------------------------------------------------------------------------- #
# Registry + dispatcher
# --------------------------------------------------------------------------- #
TOOLS: dict[str, ToolSpec] = {
    "query_metrics": ToolSpec(
        "query_metrics",
        "Time series + learned baseline + anomaly flag for one (service, metric).",
        {"service": "str", "metric": "str", "minutes": "int=30"},
        _t_query_metrics,
    ),
    "search_logs": ToolSpec(
        "search_logs",
        "Recent logs for a service with error/fatal counts and known error patterns.",
        {"service": "str", "query": "str=''", "level": "str=ERROR", "minutes": "int=30", "limit": "int=20"},
        _t_search_logs,
    ),
    "get_service_health": ToolSpec(
        "get_service_health",
        "Live health snapshot (latency p95, error rate, request rate, resources).",
        {"service": "str"},
        _t_get_service_health,
    ),
    "get_recent_deployments": ToolSpec(
        "get_recent_deployments",
        "Deployments for a service, annotated with minutes-before-incident.",
        {"service": "str", "minutes": "int=180"},
        _t_get_recent_deployments,
    ),
    "get_dependencies": ToolSpec(
        "get_dependencies",
        "Dependency graph neighbourhood + which dependencies are currently unhealthy.",
        {"service": "str"},
        _t_get_dependencies,
    ),
    "get_alert_history": ToolSpec(
        "get_alert_history",
        "Alerts fired for a service in the recent window.",
        {"service": "str", "minutes": "int=120"},
        _t_get_alert_history,
    ),
    "get_error_traces": ToolSpec(
        "get_error_traces",
        "Sample of failing distributed traces and the failing span.",
        {"service": "str", "minutes": "int=30"},
        _t_get_error_traces,
    ),
    "get_related_incidents": ToolSpec(
        "get_related_incidents",
        "Semantically similar past incidents from incident memory (RAG).",
        {"query": "str", "k": "int=3"},
        _t_get_related_incidents,
    ),
    "get_resource_usage": ToolSpec(
        "get_resource_usage",
        "CPU / memory / DB connections / queue depth snapshot for a service.",
        {"service": "str", "minutes": "int=30"},
        _t_get_resource_usage,
    ),
}


def run_tool(ctx: ToolContext, name: str, **kwargs) -> dict:
    spec = TOOLS.get(name)
    ctx._seq += 1
    started = utcnow()
    t0 = time.perf_counter()
    call = AgentToolCall(
        agent_run_id=ctx.run_id,
        sequence=ctx._seq,
        tool_name=name,
        arguments=kwargs,
        started_at=started,
    )
    if spec is None:
        call.ok = False
        call.error = f"unknown tool {name!r}"
        call.duration_ms = 0.0
        ctx.calls.append(call)
        return {"error": call.error}
    try:
        result = spec.fn(ctx, **kwargs)
        call.ok = "error" not in result
        call.error = result.get("error")
        call.result_rows = int(result.get("rows", 0))
        call.result_summary = _summarize(name, result)
    except Exception as exc:
        log.warning("tool.failed", tool=name, error=str(exc))
        result = {"error": str(exc), "rows": 0}
        call.ok = False
        call.error = str(exc)
    finally:
        call.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        ctx.calls.append(call)
    return result


def _summarize(name: str, result: dict) -> str:
    if result.get("error"):
        return f"{name}: error: {result['error']}"
    if name == "query_metrics":
        return (
            f"{result['metric']} current={result['current']} "
            f"baseline={result['baseline_mean']} z={result['zscore']} anomaly={result['anomaly']}"
        )
    if name == "search_logs":
        return f"errors={result['error_count']} fatal={result['fatal_count']} patterns={result['top_patterns']}"
    if name == "get_service_health":
        return f"health={result.get('health')} error_rate={result.get('error_rate')} p95={result.get('latency_p95_ms')}"
    if name == "get_recent_deployments":
        return f"{len(result.get('deployments', []))} deployments"
    if name == "get_dependencies":
        return (
            f"depends_on={result.get('depends_on')} unhealthy="
            f"{[d['service'] for d in result.get('unhealthy_dependencies', [])]}"
        )
    if name == "get_related_incidents":
        return f"{len(result.get('results', []))} similar incidents"
    return f"{name}: {result.get('rows', 0)} rows"
