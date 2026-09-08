"""The incident investigator agent.

Flow (spec 23):

    incident -> gather evidence via tools -> assemble bundle ->
    provider.analyze -> validate/ground -> persist evidence + hypotheses + RCA

The agent's control loop is explicit Python (an SRE playbook). The provider is
used only for the *synthesis* step and only sees the curated bundle. Provider
failure never destroys the incident - the run is marked FAILED and can be
retried (spec 63, 94).
"""

from __future__ import annotations

import traceback

from sqlalchemy.orm import Session

from nirikshan.ai.contracts import AnalysisResult
from nirikshan.ai.prompts import get_prompt
from nirikshan.ai.providers import get_llm_provider
from nirikshan.ai.tools import ToolContext, run_tool
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import ProviderUnavailable
from nirikshan.core.events import EventType, emit
from nirikshan.core.ids import run_id as new_run_id
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import AgentRunStatus, EvidenceKind
from nirikshan.incidents.engine import add_event, start_investigation_state
from nirikshan.models import (
    AgentRun,
    Incident,
    IncidentEvidence,
    IncidentHypothesis,
    LLMCall,
)

log = get_logger("ai.investigator")

_CATEGORY_TO_EVIDENCE_KIND = {
    "metric": EvidenceKind.METRIC,
    "anomaly": EvidenceKind.ANOMALY,
    "deploy": EvidenceKind.DEPLOYMENT,
    "logs": EvidenceKind.LOG,
    "dep": EvidenceKind.DEPENDENCY,
    "prior": EvidenceKind.PRIOR_INCIDENT,
    "trace": EvidenceKind.TRACE,
}


def _gather_evidence(ctx: ToolContext, service: str) -> dict:
    """Deterministic SRE playbook of tool calls -> evidence bundle."""
    inc = ctx.incident
    bundle: dict = {
        "incident": {
            "ref": inc.ref,
            "title": inc.title,
            "service": service,
            "severity": inc.severity,
            "status": inc.status,
            "detected_at": inc.detected_at.isoformat(),
            "summary": inc.summary,
        },
        "metrics": [],
        "anomalies": [],
        "deployments": [],
    }

    health = run_tool(ctx, "get_service_health", service=service)
    bundle["service_health"] = health

    for metric in (
        "request_latency_ms", "error_rate", "error_count", "request_count",
        "database_connections", "cpu_usage", "memory_usage", "queue_depth",
    ):
        m = run_tool(ctx, "query_metrics", service=service, metric=metric, minutes=40)
        if m.get("rows"):
            bundle["metrics"].append(m)
            if m.get("anomaly"):
                bundle["anomalies"].append(
                    {
                        "metric": m["metric"],
                        "score": m.get("anomaly_score"),
                        "direction": m.get("anomaly_direction") or "high",
                        "observed_value": m.get("current"),
                        "expected_high": m.get("baseline_p95"),
                        "confidence": min(0.95, 0.5 + 0.1 * (m.get("anomaly_score") or 0)),
                    }
                )

    logs = run_tool(ctx, "search_logs", service=service, level="ERROR", minutes=40, limit=25)
    bundle["logs"] = logs

    deploys = run_tool(ctx, "get_recent_deployments", service=service, minutes=180)
    bundle["deployments"] = deploys.get("deployments", [])

    deps = run_tool(ctx, "get_dependencies", service=service)
    bundle["dependencies"] = deps
    bundle["blast_radius"] = deps.get("blast_radius", {})

    alerts = run_tool(ctx, "get_alert_history", service=service, minutes=180)
    bundle["alerts"] = alerts.get("alerts", [])

    traces = run_tool(ctx, "get_error_traces", service=service, minutes=40)
    bundle["traces"] = traces

    res = run_tool(ctx, "get_resource_usage", service=service, minutes=40)
    bundle["resources"] = res.get("resources", {})

    prior_query = f"{inc.title}. {logs.get('top_patterns_text', '')}. service {service}."
    prior = run_tool(ctx, "get_related_incidents", query=prior_query, k=3)
    bundle["prior_incidents"] = prior.get("results", [])

    return bundle


def _persist_findings(
    db: Session, incident: Incident, run_id: str, bundle: dict, result: AnalysisResult
) -> None:
    # clear previous run's findings so re-investigation is idempotent
    from sqlalchemy import delete

    db.execute(delete(IncidentEvidence).where(IncidentEvidence.incident_id == incident.id))
    db.execute(delete(IncidentHypothesis).where(IncidentHypothesis.incident_id == incident.id))
    db.expire(incident, ["evidence", "hypotheses"])
    db.flush()

    ev_index = _evidence_catalog(bundle)
    seen: set[str] = set()
    for h in result.hypotheses:
        for eid in h.supporting_evidence_ids:
            if eid in seen or eid not in ev_index:
                continue
            seen.add(eid)
            meta = ev_index[eid]
            db.add(
                IncidentEvidence(
                    incident_id=incident.id,
                    run_id=run_id,
                    kind=meta["kind"].value,
                    ref_type=meta["ref_type"],
                    ref_id=meta["ref_id"],
                    summary=meta["summary"],
                    observed_at=meta.get("observed_at"),
                    weight=meta.get("weight", 0.6),
                    collected_by="investigator",
                    data=meta.get("data", {}),
                )
            )

    for i, h in enumerate(result.hypotheses, start=1):
        db.add(
            IncidentHypothesis(
                incident_id=incident.id,
                run_id=run_id,
                rank=i,
                title=h.title,
                category=h.category,
                rationale=h.rationale,
                confidence=h.confidence,
                supporting_evidence_ids=h.supporting_evidence_ids,
                is_selected=(i == 1),
            )
        )
    db.flush()


def _evidence_catalog(bundle: dict) -> dict[str, dict]:
    cat: dict[str, dict] = {}
    for m in bundle.get("metrics", []):
        cat[f"metric:{m['metric']}"] = {
            "kind": EvidenceKind.METRIC,
            "ref_type": "metric",
            "ref_id": m["metric"],
            "summary": (
                f"{m['metric']}: current={m['current']} vs baseline "
                f"{m['baseline_mean']} (z={m['zscore']}, anomaly={m['anomaly']})"
            ),
            "weight": 0.8 if m.get("anomaly") else 0.4,
            "data": {k: m.get(k) for k in ("current", "baseline_mean", "baseline_std", "zscore", "anomaly")},
        }
    for a in bundle.get("anomalies", []):
        cat[f"anomaly:{a['metric']}"] = {
            "kind": EvidenceKind.ANOMALY,
            "ref_type": "anomaly",
            "ref_id": a["metric"],
            "summary": f"anomaly on {a['metric']} score={a['score']} dir={a['direction']}",
            "weight": 0.85,
            "data": a,
        }
    for d in bundle.get("deployments", []):
        cat[f"deploy:{d['ref']}"] = {
            "kind": EvidenceKind.DEPLOYMENT,
            "ref_type": "deployment",
            "ref_id": d["ref"],
            "summary": (
                f"deployment {d['ref']} {d.get('version')} "
                f"{d.get('minutes_before_incident')} min before incident: {d.get('change_summary','')}"
            ),
            "weight": 0.8,
            "data": d,
        }
    for p in bundle.get("prior_incidents", []):
        cat[f"prior:{p['incident_ref']}"] = {
            "kind": EvidenceKind.PRIOR_INCIDENT,
            "ref_type": "incident",
            "ref_id": p["incident_ref"],
            "summary": f"similar past incident {p['incident_ref']} ({p['similarity']}): {p['root_cause']}",
            "weight": 0.5,
            "data": p,
        }
    for u in bundle.get("dependencies", {}).get("unhealthy_dependencies", []):
        cat[f"dep:unhealthy:{u['service']}"] = {
            "kind": EvidenceKind.DEPENDENCY,
            "ref_type": "service",
            "ref_id": u["service"],
            "summary": f"dependency {u['service']} is {u['health']}: {'; '.join(u.get('reasons', []))}",
            "weight": 0.9,
            "data": u,
        }
    logs = bundle.get("logs", {})
    for lid in ("logs:error_sample", "logs:connection_errors", "logs:top_patterns"):
        cat[lid] = {
            "kind": EvidenceKind.LOG,
            "ref_type": "logs",
            "ref_id": lid.split(":", 1)[1],
            "summary": (
                f"{logs.get('error_count', 0)} error logs, {logs.get('fatal_count', 0)} fatal; "
                f"patterns: {logs.get('top_patterns', [])}"
            ),
            "weight": 0.7 if logs.get("top_patterns") else 0.4,
            "data": {"error_count": logs.get("error_count"), "patterns": logs.get("top_patterns"),
                     "sample": logs.get("sample", [])[:5]},
        }
    return cat


def investigate(db: Session, incident: Incident, *, prompt_version: str | None = None, actor: str = "ai:investigator") -> AgentRun:
    provider = get_llm_provider()
    prompt = get_prompt("incident-investigator", prompt_version)
    rid = new_run_id()

    run = AgentRun(
        run_id=rid,
        kind="investigator",
        incident_id=incident.id,
        status=AgentRunStatus.RUNNING.value,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        provider=provider.name,
        model=provider.model,
        is_mock=provider.is_mock,
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()

    incident.last_investigation_run_id = rid
    start_investigation_state(db, incident)
    add_event(
        db, incident, kind="investigation_started",
        message=f"AI investigation started (run {rid}, provider={provider.name}, model={provider.model})",
        actor=actor, source="ai", data={"run_id": rid, "is_mock": provider.is_mock},
    )
    emit(EventType.INVESTIGATION_STARTED, {"incident_id": incident.id, "incident_ref": incident.ref, "run_id": rid})

    ctx = ToolContext(db=db, incident=incident, run_id=run.id, environment_id=incident.environment_id)
    try:
        bundle = _gather_evidence(ctx, incident.service_name)
        db.add_all(ctx.calls)
        db.flush()

        result = provider.analyze(bundle, prompt=prompt.body)

        _persist_findings(db, incident, rid, bundle, result)

        incident.root_cause = result.root_cause
        incident.confidence = result.confidence
        incident.contributing_factors = result.contributing_factors
        incident.recommended_actions = result.recommended_actions
        br = bundle.get("blast_radius", {})
        incident.affected_services = sorted(
            {incident.service_name, *br.get("direct_dependents", []), *br.get("indirect_dependents", [])}
        )
        # Keep the original detection summary; replace (not append) the AI block
        # so re-investigation does not grow the field unbounded.
        marker = "\n\n--- AI analysis ---\n"
        base = incident.summary.split(marker, 1)[0].rstrip()
        incident.summary = f"{base}{marker}{result.summary}".strip()
        db.add(incident)

        run.status = AgentRunStatus.COMPLETED.value
        run.finished_at = utcnow()
        run.duration_ms = round((run.finished_at - run.started_at).total_seconds() * 1000, 2)
        run.tool_call_count = len(ctx.calls)
        run.llm_call_count = 1
        run.input_tokens = result.usage.input_tokens
        run.output_tokens = result.usage.output_tokens
        from nirikshan.ai.cost import estimate_cost_usd

        run.estimated_cost_usd = estimate_cost_usd(
            provider.model, result.usage.input_tokens, result.usage.output_tokens
        )
        run.result = {
            "root_cause": result.root_cause,
            "confidence": result.confidence,
            "hypotheses": [
                {"rank": i + 1, "title": h.title, "category": h.category,
                 "confidence": h.confidence, "evidence": h.supporting_evidence_ids}
                for i, h in enumerate(result.hypotheses)
            ],
            "recommended_actions": result.recommended_actions,
            "is_mock": result.is_mock,
        }
        run.audit = {
            "prompt": {"name": prompt.name, "version": prompt.version, "checksum": prompt.checksum},
            "provider": provider.name,
            "model": provider.model,
            "is_mock": provider.is_mock,
            "tools_called": [
                {"seq": c.sequence, "tool": c.tool_name, "args": c.arguments,
                 "ok": c.ok, "rows": c.result_rows, "summary": c.result_summary,
                 "duration_ms": c.duration_ms}
                for c in ctx.calls
            ],
            "evidence_ids_available": sorted(_evidence_catalog(bundle).keys()),
            "grounded_evidence_ids": result.grounded_evidence_ids,
            "warnings": result.warnings,
            "usage": result.usage.__dict__,
        }
        db.add(run)

        db.add(
            LLMCall(
                agent_run_id=run.id,
                incident_id=incident.id,
                purpose="incident_investigation",
                provider=provider.name,
                model=provider.model,
                is_mock=provider.is_mock,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.usage.latency_ms,
                estimated_cost_usd=run.estimated_cost_usd,
                ok=True,
                created_at=utcnow(),
            )
        )

        add_event(
            db, incident, kind="rca_generated",
            message=(
                f"RCA: {result.root_cause} (confidence {result.confidence:.2f}"
                + (", DEMO/MOCK provider" if result.is_mock else "") + ")"
            ),
            actor=actor, source="ai",
            data={"run_id": rid, "confidence": result.confidence,
                  "hypotheses": [h.title for h in result.hypotheses], "is_mock": result.is_mock},
        )
        db.flush()
        emit(
            EventType.INVESTIGATION_COMPLETED,
            {"incident_id": incident.id, "incident_ref": incident.ref, "run_id": rid,
             "root_cause": result.root_cause, "confidence": result.confidence, "is_mock": result.is_mock},
        )
        log.info("investigation.completed", incident=incident.ref, run=rid, rc=result.root_cause)
        return run

    except ProviderUnavailable as exc:
        # Expected failure: session is healthy. Keep the run + gathered tool calls,
        # just mark the run FAILED so it can be retried.
        db.add_all(ctx.calls)
        return _mark_failed(db, run, incident, ctx, str(exc), session_ok=True, actor=actor)
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()[:2000]}"
        return _mark_failed(db, run, incident, ctx, err, session_ok=False, actor=actor)


def _mark_failed(db, run, incident, ctx, error: str, *, session_ok: bool, actor: str) -> AgentRun:
    if not session_ok:
        db.rollback()
        # Re-create a fresh failed run record in a clean transaction.
        run = AgentRun(
            run_id=run.run_id,
            kind="investigator",
            incident_id=incident.id,
            status=AgentRunStatus.FAILED.value,
            provider=run.provider,
            model=run.model,
            is_mock=run.is_mock,
            started_at=utcnow(),
        )
        db.add(run)
        db.flush()

    run.status = AgentRunStatus.FAILED.value
    run.finished_at = utcnow()
    if run.started_at:
        run.duration_ms = round((run.finished_at - run.started_at).total_seconds() * 1000, 2)
    run.error = error[:4000]
    run.tool_call_count = len(ctx.calls)
    run.audit = {
        "failed": True,
        "retryable": True,
        "tools_called": [
            {"seq": c.sequence, "tool": c.tool_name, "ok": c.ok, "summary": c.result_summary}
            for c in ctx.calls
        ],
    }
    db.add(run)

    inc = db.get(Incident, incident.id)
    if inc:
        inc.last_investigation_run_id = run.run_id
        add_event(
            db, inc, kind="investigation_failed",
            message=f"AI investigation failed (retryable): {error[:200]}",
            actor=actor, source="ai", data={"run_id": run.run_id},
        )
    db.add(
        LLMCall(
            agent_run_id=run.id,
            incident_id=incident.id,
            purpose="incident_investigation",
            provider=run.provider,
            model=run.model,
            is_mock=run.is_mock,
            ok=False,
            error=error[:1000],
            created_at=utcnow(),
        )
    )
    db.flush()
    emit(
        EventType.INVESTIGATION_FAILED,
        {"incident_id": incident.id, "incident_ref": incident.ref, "run_id": run.run_id,
         "error": error[:300], "retryable": True},
    )
    log.warning("investigation.failed", incident=incident.ref, run=run.run_id, error=error[:200])
    return run
