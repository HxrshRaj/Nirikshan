"""Demo-only orchestration that compresses time so the remediation loop is
observable end-to-end in seconds (spec 93).

Real operation never advances the clock; verification there simply reads
telemetry that has moved on. Here we freeze the clock a few minutes ahead,
regenerate telemetry (which now reflects the suppressed fault recovering) and
then verify - exactly the same verification code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core import clock
from nirikshan.core.logging import get_logger
from nirikshan.demo.generator import generate
from nirikshan.demo.scenarios import SCENARIOS
from nirikshan.domain.enums import IncidentStatus, Role
from nirikshan.incidents.engine import get_by_ref, resolve
from nirikshan.models import Incident, RemediationAction
from nirikshan.remediation import executor
from nirikshan.remediation.agent import propose_remediation

log = get_logger("demo.flow")


@dataclass
class RemediationFlowResult:
    incident_ref: str
    remediation_ref: str | None
    action_name: str | None
    approved: bool
    executed: bool
    verification: dict = field(default_factory=dict)
    verified: bool = False
    incident_status: str = ""
    steps: list[str] = field(default_factory=list)


def drive_remediation(
    db: Session,
    incident: Incident,
    *,
    scenario_key: str,
    approver: str = "commander@nirikshan.dev",
    approver_role: Role = Role.INCIDENT_COMMANDER,
    advance_minutes: int = 12,
) -> RemediationFlowResult:
    steps: list[str] = []
    action = db.scalar(
        select(RemediationAction).where(RemediationAction.incident_id == incident.id)
    )
    if action is None:
        action = propose_remediation(db, incident)
        steps.append("proposed remediation via AI agent")
    if action is None:
        return RemediationFlowResult(incident.ref, None, None, False, False, steps=steps + ["no action proposed"])

    executor.approve(db, action, actor=approver, actor_role=approver_role, reason="demo auto-approval")
    steps.append(f"{approver_role.value} approved {action.ref}")
    executor.execute(db, action, actor=approver)
    steps.append(f"executed {action.action_name}")
    db.flush()

    spec = SCENARIOS[scenario_key]
    clock.freeze(clock.utcnow() + timedelta(minutes=advance_minutes))
    try:
        generate(db, scenario=spec)
        steps.append(f"advanced demo clock +{advance_minutes}m and regenerated telemetry")
        report = executor.verify(db, action)
        db.refresh(action)
        steps.append(f"verification: {report['summary']}")
        verified = report["success"]
        if verified:
            inc = db.get(Incident, incident.id)
            if IncidentStatus(inc.status) not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                resolve(db, inc, actor=approver, resolution=f"Remediation {action.ref} verified successful",
                        root_cause=inc.root_cause)
                steps.append("incident resolved")
    finally:
        clock.unfreeze()

    inc = db.get(Incident, incident.id)
    return RemediationFlowResult(
        incident_ref=incident.ref,
        remediation_ref=action.ref,
        action_name=action.action_name,
        approved=True,
        executed=True,
        verification=report,
        verified=verified,
        incident_status=inc.status,
        steps=steps,
    )


def drive_by_ref(db: Session, incident_ref: str, *, scenario_key: str, **kw) -> RemediationFlowResult:
    inc = get_by_ref(db, incident_ref)
    if inc is None:
        raise KeyError(f"incident {incident_ref} not found")
    return drive_remediation(db, inc, scenario_key=scenario_key, **kw)
