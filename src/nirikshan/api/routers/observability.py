from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from starlette.responses import StreamingResponse

from nirikshan.api.deps import current_user, get_db, require_role
from nirikshan.core.clock import utcnow
from nirikshan.core.db import get_engine
from nirikshan.core.redis_bus import PUBSUB_CHANNEL, get_client, is_healthy
from nirikshan.domain.enums import OPEN_INCIDENT_STATUSES, Role
from nirikshan.models import (
    AgentRun,
    Alert,
    Anomaly,
    Deployment,
    Incident,
    RemediationAction,
    Service,
    User,
)
from nirikshan.security import audit as audit_svc
from nirikshan.telemetry.aggregate import compute_service_health

router = APIRouter(tags=["observability"])


@router.get("/health")
def health() -> dict:
    db_ok = True
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    redis_ok = is_healthy()
    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "components": {
            "database": "ok" if db_ok else "down",
            "redis": "ok" if redis_ok else "down (events/rate-limit degraded, core online)",
        },
        "time": utcnow().isoformat(),
    }


@router.get("/metrics", response_class=StreamingResponse)
def platform_metrics(db: Session = Depends(get_db)) -> StreamingResponse:
    """Prometheus-style exposition of Nirikshan's own operational metrics."""
    open_incidents = db.scalar(
        select(func.count()).select_from(Incident).where(
            Incident.status.in_([s.value for s in OPEN_INCIDENT_STATUSES])
        )
    ) or 0
    firing_alerts = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.state == "FIRING")
    ) or 0
    since = utcnow() - timedelta(hours=1)
    anomalies_1h = db.scalar(
        select(func.count()).select_from(Anomaly).where(Anomaly.detected_at >= since)
    ) or 0
    failed_runs = db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.status == "FAILED")
    ) or 0
    lines = [
        "# HELP nirikshan_open_incidents Current open incidents",
        "# TYPE nirikshan_open_incidents gauge",
        f"nirikshan_open_incidents {open_incidents}",
        "# HELP nirikshan_firing_alerts Currently firing alerts",
        "# TYPE nirikshan_firing_alerts gauge",
        f"nirikshan_firing_alerts {firing_alerts}",
        "# HELP nirikshan_anomalies_1h Anomalies detected in the last hour",
        "# TYPE nirikshan_anomalies_1h gauge",
        f"nirikshan_anomalies_1h {anomalies_1h}",
        "# HELP nirikshan_agent_runs_failed_total Failed AI agent runs",
        "# TYPE nirikshan_agent_runs_failed_total counter",
        f"nirikshan_agent_runs_failed_total {failed_runs}",
    ]
    return StreamingResponse(iter(["\n".join(lines) + "\n"]), media_type="text/plain; version=0.0.4")


@router.get("/overview")
def overview(
    db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> dict:
    now = utcnow()
    open_statuses = [s.value for s in OPEN_INCIDENT_STATUSES]
    open_incidents = list(
        db.scalars(
            select(Incident).where(Incident.status.in_(open_statuses)).order_by(Incident.detected_at.desc())
        )
    )
    services = list(db.scalars(select(Service)))
    health_rows = []
    degraded = 0
    err_rates, latencies = [], []
    for svc in services:
        snap = compute_service_health(db, svc)
        if snap.health.value in ("DEGRADED", "UNHEALTHY"):
            degraded += 1
        if snap.error_rate is not None:
            err_rates.append(snap.error_rate)
        if snap.latency_p95_ms is not None:
            latencies.append(snap.latency_p95_ms)
        health_rows.append(
            {"service": svc.name, "display_name": svc.display_name, "tier": svc.tier,
             "health": snap.health.value, "error_rate": snap.error_rate,
             "latency_p95_ms": snap.latency_p95_ms}
        )
    pending_approvals = db.scalar(
        select(func.count()).select_from(RemediationAction).where(
            RemediationAction.status == "APPROVAL_REQUIRED"
        )
    ) or 0
    recent_deploys = list(
        db.scalars(select(Deployment).order_by(Deployment.started_at.desc()).limit(5))
    )
    recent_investigations = list(
        db.scalars(
            select(AgentRun).where(AgentRun.kind == "investigator").order_by(AgentRun.created_at.desc()).limit(5)
        )
    )
    return {
        "generated_at": now.isoformat(),
        "active_incidents": len(open_incidents),
        "critical_incidents": sum(1 for i in open_incidents if i.severity in ("SEV-1", "SEV-2")),
        "services_total": len(services),
        "services_degraded": degraded,
        "error_rate_avg": round(sum(err_rates) / len(err_rates), 5) if err_rates else 0.0,
        "latency_p95_avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "alert_volume_24h": db.scalar(
            select(func.count()).select_from(Alert).where(Alert.fired_at >= now - timedelta(hours=24))
        ) or 0,
        "anomalies_1h": db.scalar(
            select(func.count()).select_from(Anomaly).where(Anomaly.detected_at >= now - timedelta(hours=1))
        ) or 0,
        "pending_approvals": pending_approvals,
        "open_incidents": [
            {"ref": i.ref, "title": i.title, "severity": i.severity, "status": i.status,
             "service": i.service_name, "detected_at": i.detected_at.isoformat(), "confidence": i.confidence}
            for i in open_incidents[:10]
        ],
        "service_health": health_rows,
        "recent_deployments": [
            {"ref": d.ref, "service": d.service_name, "version": d.version,
             "started_at": d.started_at.isoformat(), "status": d.status}
            for d in recent_deploys
        ],
        "recent_investigations": [
            {"run_id": r.run_id, "incident_id": r.incident_id, "status": r.status,
             "is_mock": r.is_mock, "root_cause": (r.result or {}).get("root_cause"),
             "confidence": (r.result or {}).get("confidence")}
            for r in recent_investigations
        ],
    }


@router.get("/audit")
def audit_log(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.INCIDENT_COMMANDER)),
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    rows, total = audit_svc.list_audit(
        db, resource_type=resource_type, resource_id=resource_id, actor=actor, limit=limit, offset=offset
    )
    return {
        "total": total,
        "items": [
            {"id": r.id, "at": r.at.isoformat(), "actor": r.actor, "actor_role": r.actor_role,
             "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id,
             "result": r.result, "ip": r.ip, "before": r.before, "after": r.after, "note": r.note}
            for r in rows
        ],
    }


@router.get("/stream")
async def event_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events feed mirrored from the Redis pub/sub channel."""

    async def gen():
        try:
            client = get_client()
            pubsub = client.pubsub()
            pubsub.subscribe(PUBSUB_CHANNEL)
        except Exception:
            while not await request.is_disconnected():
                yield ": redis-unavailable\n\n"
                await asyncio.sleep(15)
            return
        yield 'event: hello\ndata: {"ok": true}\n\n'
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    yield f"data: {msg['data']}\n\n"
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(0.2)
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
