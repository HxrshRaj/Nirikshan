"""ORM -> API schema conversion helpers."""

from __future__ import annotations

from nirikshan.core.clock import utcnow
from nirikshan.models import (
    AgentRun,
    Alert,
    Anomaly,
    Deployment,
    Incident,
    RemediationAction,
    Service,
)
from nirikshan.schemas.agents import AgentRunDetail, AgentRunSummary, ToolCallOut
from nirikshan.schemas.alerting import AlertOut, AnomalyOut
from nirikshan.schemas.catalog import DeploymentOut, ServiceOut
from nirikshan.schemas.incidents import (
    EvidenceOut,
    HypothesisOut,
    IncidentDetail,
    IncidentEventOut,
    IncidentSummary,
)
from nirikshan.schemas.remediation import ApprovalOut, ExecutionOut, RemediationOut


def _duration(inc: Incident) -> float | None:
    end = inc.resolved_at or utcnow()
    if not inc.detected_at:
        return None
    return round((end - inc.detected_at).total_seconds(), 1)


def service_out(svc: Service, *, depends_on: list[str] | None = None, upstream_of: list[str] | None = None) -> ServiceOut:
    return ServiceOut(
        id=svc.id,
        name=svc.name,
        display_name=svc.display_name,
        environment=svc.environment.name if svc.environment else "",
        kind=svc.kind,
        tier=svc.tier,
        owner_team=svc.owner_team,
        runbook_url=svc.runbook_url,
        health=svc.health,
        health_updated_at=svc.health_updated_at,
        slo_latency_ms_p95=svc.slo_latency_ms_p95,
        slo_error_rate=svc.slo_error_rate,
        attributes=svc.attributes or {},
        depends_on=depends_on or [],
        upstream_of=upstream_of or [],
    )


def incident_summary(inc: Incident) -> IncidentSummary:
    return IncidentSummary(
        id=inc.id,
        ref=inc.ref,
        title=inc.title,
        severity=inc.severity,
        status=inc.status,
        service=inc.service_name,
        environment_id=inc.environment_id,
        detected_at=inc.detected_at,
        acknowledged_at=inc.acknowledged_at,
        resolved_at=inc.resolved_at,
        confidence=inc.confidence,
        alert_count=inc.alert_count,
        affected_services=inc.affected_services or [],
        duration_seconds=_duration(inc),
    )


def evidence_out(e) -> EvidenceOut:
    return EvidenceOut(
        id=e.id, kind=e.kind, ref_type=e.ref_type, ref_id=e.ref_id, summary=e.summary,
        observed_at=e.observed_at, weight=e.weight, collected_by=e.collected_by, data=e.data or {},
    )


def hypothesis_out(h) -> HypothesisOut:
    return HypothesisOut(
        id=h.id, rank=h.rank, title=h.title, category=h.category, rationale=h.rationale,
        confidence=h.confidence, supporting_evidence_ids=h.supporting_evidence_ids or [],
        is_selected=h.is_selected,
    )


def incident_detail(inc: Incident) -> IncidentDetail:
    base = incident_summary(inc).model_dump()
    return IncidentDetail(
        **base,
        summary=inc.summary,
        root_cause=inc.root_cause,
        contributing_factors=inc.contributing_factors or [],
        recommended_actions=inc.recommended_actions or [],
        blast_radius=inc.blast_radius or {},
        correlated_alert_refs=inc.correlated_alert_refs or [],
        acknowledged_by=inc.acknowledged_by,
        resolved_by=inc.resolved_by,
        last_investigation_run_id=inc.last_investigation_run_id,
        events=[
            IncidentEventOut(
                id=ev.id, at=ev.at, kind=ev.kind, message=ev.message, actor=ev.actor,
                source=ev.source, data=ev.data or {},
            )
            for ev in sorted(inc.events, key=lambda x: x.at)
        ],
        evidence=[evidence_out(e) for e in inc.evidence],
        hypotheses=[hypothesis_out(h) for h in sorted(inc.hypotheses, key=lambda x: x.rank)],
    )


def alert_out(a: Alert) -> AlertOut:
    return AlertOut(
        id=a.id, ref=a.ref, rule_id=a.rule_id, service=a.service_name, environment_id=a.environment_id,
        title=a.title, signal_kind=a.signal_kind, subject=a.subject, severity=a.severity, state=a.state,
        observed_value=a.observed_value, threshold=a.threshold, fired_at=a.fired_at,
        resolved_at=a.resolved_at, fingerprint=a.fingerprint, incident_id=a.incident_id,
        context=a.context or {},
    )


def anomaly_out(a: Anomaly) -> AnomalyOut:
    return AnomalyOut(
        id=a.id, detected_at=a.detected_at, service=a.service_name, metric_name=a.metric_name,
        method=a.method, observed_value=a.observed_value, expected_low=a.expected_low,
        expected_high=a.expected_high, score=a.score, confidence=a.confidence, direction=a.direction,
        context=a.context or {},
    )


def deployment_out(d: Deployment) -> DeploymentOut:
    return DeploymentOut(
        id=d.id, ref=d.ref, service=d.service_name, environment_id=d.environment_id, version=d.version,
        previous_version=d.previous_version, commit_sha=d.commit_sha, change_summary=d.change_summary,
        started_at=d.started_at, completed_at=d.completed_at, status=d.status, triggered_by=d.triggered_by,
    )


def agent_run_summary(r: AgentRun) -> AgentRunSummary:
    return AgentRunSummary(
        id=r.id, run_id=r.run_id, kind=r.kind, incident_id=r.incident_id, status=r.status,
        provider=r.provider, model=r.model, is_mock=r.is_mock, started_at=r.started_at,
        finished_at=r.finished_at, duration_ms=r.duration_ms, tool_call_count=r.tool_call_count,
        llm_call_count=r.llm_call_count, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
        estimated_cost_usd=r.estimated_cost_usd, error=r.error,
    )


def agent_run_detail(r: AgentRun) -> AgentRunDetail:
    base = agent_run_summary(r).model_dump()
    return AgentRunDetail(
        **base,
        prompt_name=r.prompt_name,
        prompt_version=r.prompt_version,
        result=r.result or {},
        audit=r.audit or {},
        tool_calls=[
            ToolCallOut(
                sequence=c.sequence, tool_name=c.tool_name, arguments=c.arguments or {}, ok=c.ok,
                error=c.error, result_summary=c.result_summary, result_rows=c.result_rows,
                duration_ms=c.duration_ms,
            )
            for c in sorted(r.tool_calls, key=lambda x: x.sequence)
        ],
    )


def remediation_out(a: RemediationAction) -> RemediationOut:
    return RemediationOut(
        id=a.id, ref=a.ref, incident_id=a.incident_id, proposed_by_run_id=a.proposed_by_run_id,
        action_name=a.action_name, parameters=a.parameters or {}, rationale=a.rationale, risk=a.risk,
        expected_impact=a.expected_impact, rollback_plan=a.rollback_plan,
        verification_plan=a.verification_plan or {}, status=a.status, mode=a.mode,
        policy_findings=a.policy_findings or [], is_reversible=a.is_reversible, created_at=a.created_at,
        approvals=[
            ApprovalOut(id=p.id, decision=p.decision, actor=p.actor, actor_role=p.actor_role,
                        reason=p.reason, at=p.at)
            for p in sorted(a.approvals, key=lambda x: x.at)
        ],
        executions=[
            ExecutionOut(
                id=e.id, attempt=e.attempt, kind=e.kind, actor=e.actor, started_at=e.started_at,
                finished_at=e.finished_at, ok=e.ok, result=e.result, before_state=e.before_state or {},
                after_state=e.after_state or {}, verification=e.verification or {}, log=e.log,
            )
            for e in sorted(a.executions, key=lambda x: x.created_at)
        ],
    )
