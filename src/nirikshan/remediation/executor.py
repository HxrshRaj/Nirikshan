"""Approval + safe execution + verification + rollback of remediation actions.

Nothing here ever runs an LLM-authored command. It looks the action up in the
registry by name, validates parameters, re-checks policy, then calls the
registry's typed ``apply`` / ``revert`` function against demo runtime state.
Every step is recorded (before/after state, actor, approval, result) for the
audit trail and rollback (spec 34).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.errors import ConflictError, PermissionError_, PolicyViolation
from nirikshan.core.events import EventType, emit
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import (
    IncidentStatus,
    RemediationStatus,
    Role,
)
from nirikshan.incidents.engine import add_event, transition
from nirikshan.models import Incident, RemediationAction, RemediationApproval, RemediationExecution
from nirikshan.remediation.policy import evaluate as evaluate_policy
from nirikshan.remediation.registry import get_action, resolve_service
from nirikshan.remediation.verification import run_verification

log = get_logger("remediation.executor")

_ACTIVE = {
    RemediationStatus.APPROVAL_REQUIRED.value,
    RemediationStatus.PROPOSED.value,
    RemediationStatus.APPROVED.value,
}


def _incident(db: Session, action: RemediationAction) -> Incident:
    inc = db.get(Incident, action.incident_id)
    assert inc is not None
    return inc


def _snapshot(db: Session, service_name: str) -> dict:
    from nirikshan.remediation.registry import runtime_state
    from nirikshan.telemetry.aggregate import health_for

    snap = health_for(db, service_name)
    svc = resolve_service(db, {"service": service_name})
    return {
        "health": snap.as_dict() if snap else None,
        "runtime": runtime_state(svc),
        "at": utcnow().isoformat(),
    }


def approve(
    db: Session, action: RemediationAction, *, actor: str, actor_role: Role, reason: str = ""
) -> RemediationAction:
    if action.status not in _ACTIVE:
        raise ConflictError(f"remediation {action.ref} is {action.status}; cannot approve")
    incident = _incident(db, action)
    decision = evaluate_policy(
        db,
        incident=incident,
        action_name=action.action_name,
        parameters=action.parameters,
        risk=action.risk,
        rca_confidence=incident.confidence,
        actor_role=actor_role,
    )
    if decision.blocked:
        raise PolicyViolation(
            f"policy blocks remediation {action.ref}", details={"findings": decision.as_list()}
        )
    if actor_role.rank < decision.min_role.rank:
        raise PermissionError_(
            f"{actor_role.value} cannot approve remediation {action.ref}; "
            f"requires {decision.min_role.value} or higher"
        )

    db.add(
        RemediationApproval(
            action_id=action.id,
            decision="approved",
            actor=actor,
            actor_role=actor_role.value,
            reason=reason,
            at=utcnow(),
        )
    )
    action.status = RemediationStatus.APPROVED.value
    db.add(action)
    add_event(
        db, incident, kind="remediation_approved",
        message=f"Remediation {action.ref} approved by {actor} ({actor_role.value})",
        actor=actor, source="human", data={"remediation_ref": action.ref, "reason": reason},
    )
    db.flush()
    emit(
        EventType.REMEDIATION_APPROVED,
        {"incident_id": incident.id, "incident_ref": incident.ref, "remediation_ref": action.ref, "actor": actor},
    )
    return action


def reject(
    db: Session, action: RemediationAction, *, actor: str, actor_role: Role, reason: str = ""
) -> RemediationAction:
    if action.status not in _ACTIVE:
        raise ConflictError(f"remediation {action.ref} is {action.status}; cannot reject")
    incident = _incident(db, action)
    db.add(
        RemediationApproval(
            action_id=action.id, decision="rejected", actor=actor,
            actor_role=actor_role.value, reason=reason, at=utcnow(),
        )
    )
    action.status = RemediationStatus.REJECTED.value
    db.add(action)
    add_event(
        db, incident, kind="remediation_rejected",
        message=f"Remediation {action.ref} rejected by {actor}: {reason or 'no reason given'}",
        actor=actor, source="human", data={"remediation_ref": action.ref},
    )
    db.flush()
    emit(EventType.REMEDIATION_REJECTED, {"incident_id": incident.id, "remediation_ref": action.ref})
    return action


def execute(db: Session, action: RemediationAction, *, actor: str = "system") -> RemediationExecution:
    if action.status != RemediationStatus.APPROVED.value:
        raise ConflictError(f"remediation {action.ref} must be APPROVED before execution (is {action.status})")
    incident = _incident(db, action)
    spec = get_action(action.action_name)
    service = resolve_service(db, action.parameters)

    attempt = len([e for e in action.executions if e.kind == "apply"]) + 1
    now = utcnow()
    execution = RemediationExecution(
        action_id=action.id,
        attempt=attempt,
        kind="apply",
        actor=actor,
        started_at=now,
        created_at=now,
        before_state=_snapshot(db, service.name),
        result="running",
    )
    db.add(execution)
    action.status = RemediationStatus.EXECUTING.value
    db.add(action)
    if IncidentStatus(incident.status) not in (IncidentStatus.MITIGATING, IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        try:
            transition(db, incident, IncidentStatus.MITIGATING, actor=actor, source="system",
                       note=f"executing remediation {action.ref}")
        except Exception:
            pass
    add_event(
        db, incident, kind="remediation_started",
        message=f"Executing remediation {action.ref}: {action.action_name} {action.parameters}",
        actor=actor, source="system", data={"remediation_ref": action.ref, "attempt": attempt},
    )
    db.flush()
    emit(EventType.REMEDIATION_STARTED, {"incident_id": incident.id, "remediation_ref": action.ref})

    try:
        outcome = spec.apply(db, service, action.parameters)
        execution.ok = True
        execution.result = "applied"
        execution.log = f"applied {action.action_name}: {outcome}"
        execution.after_state = _snapshot(db, service.name)
        execution.verification = {}
        execution.finished_at = utcnow()
        action.status = RemediationStatus.VERIFYING.value
        db.add_all([execution, action])
        add_event(
            db, incident, kind="remediation_applied",
            message=f"Remediation {action.ref} applied: {outcome}",
            actor=actor, source="system", data={"remediation_ref": action.ref, "outcome": outcome},
        )
        db.flush()
        emit(EventType.REMEDIATION_COMPLETED,
             {"incident_id": incident.id, "remediation_ref": action.ref, "phase": "applied"})
    except Exception as exc:
        execution.ok = False
        execution.result = "failed"
        execution.log = f"apply failed: {exc}"
        execution.finished_at = utcnow()
        action.status = RemediationStatus.FAILED.value
        db.add_all([execution, action])
        add_event(
            db, incident, kind="remediation_failed",
            message=f"Remediation {action.ref} failed during apply: {exc}",
            actor=actor, source="system", data={"remediation_ref": action.ref, "error": str(exc)},
        )
        db.flush()
        emit(EventType.REMEDIATION_FAILED,
             {"incident_id": incident.id, "remediation_ref": action.ref, "error": str(exc)})
    return execution


def verify(db: Session, action: RemediationAction, *, actor: str = "system") -> dict:
    if action.status not in (RemediationStatus.VERIFYING.value, RemediationStatus.EXECUTING.value):
        raise ConflictError(f"remediation {action.ref} is not in a verifiable state ({action.status})")
    incident = _incident(db, action)
    report = run_verification(db, action.verification_plan or {})
    execution = next((e for e in reversed(action.executions) if e.kind == "apply"), None)
    if execution:
        execution.verification = report
        db.add(execution)

    if report["success"]:
        action.status = RemediationStatus.SUCCEEDED.value
        add_event(
            db, incident, kind="remediation_verified",
            message=f"Remediation {action.ref} verified successful: {report['summary']}",
            actor=actor, source="system", data={"remediation_ref": action.ref, "verification": report},
        )
        emit(EventType.REMEDIATION_COMPLETED,
             {"incident_id": incident.id, "remediation_ref": action.ref, "phase": "verified", "success": True})
    else:
        action.status = RemediationStatus.FAILED.value
        add_event(
            db, incident, kind="remediation_verification_failed",
            message=f"Remediation {action.ref} verification failed: {report['summary']}",
            actor=actor, source="system", data={"remediation_ref": action.ref, "verification": report},
        )
        emit(EventType.REMEDIATION_FAILED,
             {"incident_id": incident.id, "remediation_ref": action.ref, "phase": "verification"})
    db.add(action)
    db.flush()
    return report


def rollback(db: Session, action: RemediationAction, *, actor: str) -> RemediationExecution:
    spec = get_action(action.action_name)
    if not spec.reversible or spec.revert is None:
        raise ConflictError(f"remediation {action.ref} ({action.action_name}) is not reversible")
    if action.status not in (
        RemediationStatus.SUCCEEDED.value,
        RemediationStatus.FAILED.value,
        RemediationStatus.VERIFYING.value,
    ):
        raise ConflictError(f"remediation {action.ref} is {action.status}; cannot roll back")
    incident = _incident(db, action)
    service = resolve_service(db, action.parameters)
    now = utcnow()
    execution = RemediationExecution(
        action_id=action.id,
        attempt=len(action.executions) + 1,
        kind="rollback",
        actor=actor,
        started_at=now,
        created_at=now,
        before_state=_snapshot(db, service.name),
        result="running",
    )
    db.add(execution)
    try:
        outcome = spec.revert(db, service, action.parameters)
        execution.ok = True
        execution.result = "rolled_back"
        execution.after_state = _snapshot(db, service.name)
        execution.finished_at = utcnow()
        execution.log = f"reverted {action.action_name}: {outcome}"
        action.status = RemediationStatus.ROLLED_BACK.value
        db.add_all([execution, action])
        add_event(
            db, incident, kind="remediation_rolled_back",
            message=f"Remediation {action.ref} rolled back by {actor}: {outcome}",
            actor=actor, source="human", data={"remediation_ref": action.ref, "outcome": outcome},
        )
        db.flush()
        emit(EventType.REMEDIATION_ROLLED_BACK,
             {"incident_id": incident.id, "remediation_ref": action.ref, "actor": actor})
    except Exception as exc:
        execution.ok = False
        execution.result = "failed"
        execution.finished_at = utcnow()
        execution.log = f"rollback failed: {exc}"
        db.add(execution)
        add_event(
            db, incident, kind="remediation_rollback_failed",
            message=f"Rollback of {action.ref} failed: {exc}",
            actor=actor, source="human", data={"remediation_ref": action.ref, "error": str(exc)},
        )
        db.flush()
    return execution
