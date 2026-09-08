"""Remediation planning agent (spec 28).

Input : incident + RCA + evidence + system context
Output: a single registered action with rationale, risk, expected impact,
        rollback plan and verification plan - persisted as a RemediationAction
        in status PROPOSED / APPROVAL_REQUIRED (never auto-executed here).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.ai.cost import estimate_cost_usd
from nirikshan.ai.prompts import get_prompt
from nirikshan.ai.providers import get_llm_provider
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import ConflictError, ProviderUnavailable
from nirikshan.core.events import EventType, emit
from nirikshan.core.ids import run_id as new_run_id
from nirikshan.core.ids import short_token
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import (
    AgentRunStatus,
    IncidentStatus,
    RemediationStatus,
)
from nirikshan.incidents.engine import add_event
from nirikshan.models import (
    AgentRun,
    Deployment,
    Incident,
    IncidentHypothesis,
    LLMCall,
    RemediationAction,
)
from nirikshan.remediation.policy import evaluate as evaluate_policy
from nirikshan.remediation.registry import get_action

log = get_logger("remediation.agent")


def _build_context(db: Session, incident: Incident) -> dict:
    top = db.scalar(
        select(IncidentHypothesis)
        .where(IncidentHypothesis.incident_id == incident.id)
        .order_by(IncidentHypothesis.rank)
        .limit(1)
    )
    category = top.category if top else "inconclusive"

    recent_deploy = None
    dep = db.scalar(
        select(Deployment)
        .where(Deployment.service_id == incident.service_id, Deployment.started_at <= incident.detected_at)
        .order_by(Deployment.started_at.desc())
        .limit(1)
    )
    if dep:
        mins = (incident.detected_at - (dep.completed_at or dep.started_at)).total_seconds() / 60.0
        if -2 <= mins <= 45 and dep.triggered_by != "nirikshan-remediation":
            recent_deploy = {
                "ref": dep.ref,
                "version": dep.version,
                "previous_version": dep.previous_version,
                "minutes_before_incident": round(mins, 1),
            }

    from nirikshan.models import Service
    from nirikshan.telemetry.aggregate import compute_service_health

    svc = db.get(Service, incident.service_id)
    health = compute_service_health(db, svc)
    return {
        "incident_ref": incident.ref,
        "service": incident.service_name,
        "environment_id": incident.environment_id,
        "severity": incident.severity,
        "status": incident.status,
        "category": category,
        "rca": incident.root_cause,
        "rca_confidence": incident.confidence or (top.confidence if top else 0.4),
        "contributing_factors": incident.contributing_factors or [],
        "recommended_actions": incident.recommended_actions or [],
        "recent_deployment": recent_deploy,
        "unhealthy_dependencies": (incident.blast_radius or {}).get("unhealthy_dependencies", []),
        "slo": {"error_rate": svc.slo_error_rate, "latency_ms_p95": svc.slo_latency_ms_p95},
        "db_involved": category == "database_saturation" or "database" in (incident.root_cause or "").lower(),
        "db_ceiling": 100,
        "health": health.as_dict(),
        "blast_radius": incident.blast_radius or {},
    }


def propose_remediation(
    db: Session, incident: Incident, *, actor: str = "ai:remediation", force: bool = False
) -> RemediationAction | None:
    if IncidentStatus(incident.status) in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        raise ConflictError(f"incident {incident.ref} is {incident.status}; cannot propose remediation")

    open_existing = db.scalar(
        select(RemediationAction).where(
            RemediationAction.incident_id == incident.id,
            RemediationAction.status.in_(
                [
                    RemediationStatus.PROPOSED.value,
                    RemediationStatus.APPROVAL_REQUIRED.value,
                    RemediationStatus.APPROVED.value,
                    RemediationStatus.EXECUTING.value,
                    RemediationStatus.VERIFYING.value,
                ]
            ),
        )
    )
    if open_existing and not force:
        raise ConflictError(
            f"incident {incident.ref} already has an open remediation ({open_existing.ref})"
        )

    provider = get_llm_provider()
    prompt = get_prompt("remediation-agent")
    rid = new_run_id()
    run = AgentRun(
        run_id=rid,
        kind="remediation",
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

    context = _build_context(db, incident)
    try:
        plan = provider.plan_remediation(context, prompt=prompt.body)
    except ProviderUnavailable as exc:
        run.status = AgentRunStatus.FAILED.value
        run.finished_at = utcnow()
        run.error = str(exc)
        db.add(run)
        add_event(
            db, incident, kind="remediation_failed",
            message=f"Remediation planning failed: {exc}", actor=actor, source="ai",
            data={"run_id": rid},
        )
        db.flush()
        emit(EventType.REMEDIATION_FAILED, {"incident_id": incident.id, "run_id": rid, "error": str(exc)})
        return None

    if plan is None:
        run.status = AgentRunStatus.COMPLETED.value
        run.finished_at = utcnow()
        run.result = {"proposed": False, "reason": "RCA inconclusive or confidence too low for a safe action"}
        db.add(run)
        add_event(
            db, incident, kind="remediation_skipped",
            message="Remediation agent proposed no action (inconclusive / low-confidence RCA)",
            actor=actor, source="ai", data={"run_id": rid},
        )
        db.flush()
        return None

    # Validate action against the registry (defence in depth; provider already validated).
    spec = get_action(plan.action_name)
    spec.validate_params(plan.parameters)

    decision = evaluate_policy(
        db,
        incident=incident,
        action_name=plan.action_name,
        parameters=plan.parameters,
        risk=plan.risk,
        rca_confidence=context["rca_confidence"],
    )

    status = (
        RemediationStatus.APPROVAL_REQUIRED.value
        if decision.requires_approval
        else RemediationStatus.PROPOSED.value
    )
    if decision.blocked:
        status = RemediationStatus.PROPOSED.value

    action = RemediationAction(
        ref="REM-" + short_token(6),
        incident_id=incident.id,
        proposed_by_run_id=rid,
        action_name=plan.action_name,
        parameters=plan.parameters,
        rationale=plan.rationale,
        risk=plan.risk,
        expected_impact=plan.expected_impact,
        rollback_plan=plan.rollback_plan,
        verification_plan=plan.verification,
        status=status,
        mode=decision.effective_mode.value,
        policy_findings=decision.as_list(),
        is_reversible=spec.reversible,
    )
    db.add(action)
    db.flush()

    run.status = AgentRunStatus.COMPLETED.value
    run.finished_at = utcnow()
    run.duration_ms = round((run.finished_at - run.started_at).total_seconds() * 1000, 2)
    run.llm_call_count = 1
    run.input_tokens = plan.usage.input_tokens
    run.output_tokens = plan.usage.output_tokens
    run.estimated_cost_usd = estimate_cost_usd(
        provider.model, plan.usage.input_tokens, plan.usage.output_tokens
    )
    run.result = {
        "proposed": True,
        "remediation_ref": action.ref,
        "action": plan.action_name,
        "parameters": plan.parameters,
        "risk": plan.risk,
        "requires_approval": decision.requires_approval,
        "min_role": decision.min_role.value,
        "is_mock": plan.is_mock,
    }
    run.audit = {
        "prompt": {"name": prompt.name, "version": prompt.version, "checksum": prompt.checksum},
        "provider": provider.name,
        "model": provider.model,
        "is_mock": provider.is_mock,
        "context": context,
        "policy_findings": decision.as_list(),
        "alternatives": plan.alternatives,
        "usage": plan.usage.__dict__,
    }
    db.add(run)
    db.add(
        LLMCall(
            agent_run_id=run.id,
            incident_id=incident.id,
            purpose="remediation_planning",
            provider=provider.name,
            model=provider.model,
            is_mock=provider.is_mock,
            input_tokens=plan.usage.input_tokens,
            output_tokens=plan.usage.output_tokens,
            latency_ms=plan.usage.latency_ms,
            estimated_cost_usd=run.estimated_cost_usd,
            ok=True,
            created_at=utcnow(),
        )
    )
    add_event(
        db, incident, kind="remediation_proposed",
        message=(
            f"AI proposed remediation {action.ref}: {plan.action_name} "
            f"(risk {plan.risk}, {'approval required' if decision.requires_approval else 'auto-eligible'}"
            + (", DEMO/MOCK" if plan.is_mock else "") + ")"
        ),
        actor=actor, source="ai",
        data={"remediation_ref": action.ref, "action": plan.action_name, "risk": plan.risk,
              "requires_approval": decision.requires_approval, "is_mock": plan.is_mock},
    )
    db.flush()
    emit(
        EventType.REMEDIATION_PROPOSED,
        {"incident_id": incident.id, "incident_ref": incident.ref, "remediation_ref": action.ref,
         "action": plan.action_name, "risk": plan.risk, "requires_approval": decision.requires_approval},
    )
    log.info("remediation.proposed", incident=incident.ref, ref=action.ref, action=plan.action_name)
    return action
