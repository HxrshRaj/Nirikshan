from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db
from nirikshan.api.serializers import agent_run_detail, agent_run_summary
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import NotFoundError
from nirikshan.models import AgentRun, LLMCall, User
from nirikshan.schemas.agents import AgentRunDetail, AgentRunSummary

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[AgentRunSummary])
def list_runs(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    kind: str | None = None,
    incident_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentRunSummary]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
    if kind:
        stmt = stmt.where(AgentRun.kind == kind)
    if incident_id:
        stmt = stmt.where(AgentRun.incident_id == incident_id)
    if status:
        stmt = stmt.where(AgentRun.status == status.upper())
    return [agent_run_summary(r) for r in db.scalars(stmt)]


@router.get("/agents/ops/summary")
def ops_summary(
    db: Session = Depends(get_db), _u: User = Depends(current_user), hours: int = Query(default=24, ge=1, le=720)
) -> dict:
    """AI cost / latency / usage rollup for the operations view (spec 67, 68)."""
    since = utcnow() - timedelta(hours=hours)
    calls = list(db.scalars(select(LLMCall).where(LLMCall.created_at >= since)))
    runs = list(db.scalars(select(AgentRun).where(AgentRun.created_at >= since)))
    by_provider: dict[str, dict] = {}
    for c in calls:
        p = by_provider.setdefault(c.provider, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                "cost_usd": 0.0, "errors": 0, "latency_ms_sum": 0.0})
        p["calls"] += 1
        p["input_tokens"] += c.input_tokens
        p["output_tokens"] += c.output_tokens
        p["cost_usd"] += c.estimated_cost_usd
        p["errors"] += 0 if c.ok else 1
        p["latency_ms_sum"] += c.latency_ms
    for p in by_provider.values():
        p["avg_latency_ms"] = round(p["latency_ms_sum"] / p["calls"], 1) if p["calls"] else 0
        p["cost_usd"] = round(p["cost_usd"], 6)
        del p["latency_ms_sum"]
    durations = [r.duration_ms for r in runs if r.duration_ms]
    return {
        "window_hours": hours,
        "agent_runs": {
            "total": len(runs),
            "completed": sum(1 for r in runs if r.status == "COMPLETED"),
            "failed": sum(1 for r in runs if r.status == "FAILED"),
            "by_kind": _count_by(runs, "kind"),
            "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0,
            "p95_duration_ms": _p95(durations),
            "total_tool_calls": sum(r.tool_call_count for r in runs),
        },
        "llm_calls": {
            "total": len(calls),
            "mock": sum(1 for c in calls if c.is_mock),
            "by_provider": by_provider,
            "total_cost_usd": round(sum(c.estimated_cost_usd for c in calls), 6),
        },
    }


def _count_by(rows, attr: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[getattr(r, attr)] = out.get(getattr(r, attr), 0) + 1
    return out


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(int(0.95 * (len(s) - 1)), len(s) - 1)], 1)


@router.get("/agents/{run_id}", response_model=AgentRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> AgentRunDetail:
    r = db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
    if r is None:
        r = db.get(AgentRun, run_id)
    if r is None:
        raise NotFoundError(f"agent run {run_id} not found")
    return agent_run_detail(r)
