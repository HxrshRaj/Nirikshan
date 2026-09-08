from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, rate_limit, require_role
from nirikshan.api.serializers import remediation_out
from nirikshan.core.errors import NotFoundError
from nirikshan.domain.enums import Role
from nirikshan.incidents.engine import get_by_ref
from nirikshan.models import RemediationAction, User
from nirikshan.remediation import executor
from nirikshan.remediation.agent import propose_remediation
from nirikshan.remediation.registry import REGISTRY
from nirikshan.schemas.remediation import (
    ActionSpecOut,
    ApprovalIn,
    RemediationOut,
    RemediationProposeIn,
)
from nirikshan.security import audit

router = APIRouter(tags=["remediations"])

_rl = Depends(rate_limit("remediation"))


def _get(db: Session, ref: str) -> RemediationAction:
    a = db.scalar(select(RemediationAction).where(RemediationAction.ref == ref))
    if a is None:
        raise NotFoundError(f"remediation {ref} not found")
    return a


@router.get("/remediations/actions", response_model=list[ActionSpecOut])
def action_registry(_u: User = Depends(current_user)) -> list[ActionSpecOut]:
    return [
        ActionSpecOut(
            name=s.name, description=s.description, parameters_schema=s.parameters_schema,
            default_risk=s.default_risk, reversible=s.reversible, requires_role=s.requires_role.value,
        )
        for s in REGISTRY.values()
    ]


@router.get("/remediations", response_model=list[RemediationOut])
def list_remediations(
    db: Session = Depends(get_db), _u: User = Depends(current_user), status: str | None = None
) -> list[RemediationOut]:
    stmt = select(RemediationAction).order_by(RemediationAction.created_at.desc())
    if status:
        stmt = stmt.where(RemediationAction.status == status.upper())
    return [remediation_out(a) for a in db.scalars(stmt)]


@router.get("/remediations/{ref}", response_model=RemediationOut)
def get_remediation(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> RemediationOut:
    return remediation_out(_get(db, ref))


@router.post("/incidents/{incident_ref}/remediation", response_model=RemediationOut, dependencies=[_rl])
def propose(
    incident_ref: str, payload: RemediationProposeIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.ENGINEER)),
) -> RemediationOut:
    inc = get_by_ref(db, incident_ref)
    if inc is None:
        raise NotFoundError(f"incident {incident_ref} not found")
    action = propose_remediation(db, inc, force=payload.force)
    if action is None:
        raise NotFoundError("remediation agent proposed no action (inconclusive / low-confidence RCA)")
    audit.record(db, actor=user.email, actor_role=user.role, action="remediation.propose",
                 resource_type="incident", resource_id=inc.ref,
                 after={"remediation_ref": action.ref, "action": action.action_name})
    return remediation_out(action)


@router.post("/remediations/{ref}/approve", response_model=RemediationOut, dependencies=[_rl])
def approve(
    ref: str, payload: ApprovalIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.INCIDENT_COMMANDER)),
) -> RemediationOut:
    action = _get(db, ref)
    executor.approve(db, action, actor=user.email, actor_role=Role(user.role), reason=payload.reason)
    executor.execute(db, action, actor=user.email)
    audit.record(db, actor=user.email, actor_role=user.role, action="remediation.approve",
                 resource_type="remediation", resource_id=action.ref, note=payload.reason)
    db.refresh(action)
    return remediation_out(action)


@router.post("/remediations/{ref}/reject", response_model=RemediationOut, dependencies=[_rl])
def reject(
    ref: str, payload: ApprovalIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.INCIDENT_COMMANDER)),
) -> RemediationOut:
    action = _get(db, ref)
    executor.reject(db, action, actor=user.email, actor_role=Role(user.role), reason=payload.reason)
    audit.record(db, actor=user.email, actor_role=user.role, action="remediation.reject",
                 resource_type="remediation", resource_id=action.ref, note=payload.reason)
    return remediation_out(action)


@router.post("/remediations/{ref}/verify", response_model=RemediationOut, dependencies=[_rl])
def verify(
    ref: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.ENGINEER))
) -> RemediationOut:
    action = _get(db, ref)
    executor.verify(db, action, actor=user.email)
    db.refresh(action)
    return remediation_out(action)


@router.post("/remediations/{ref}/rollback", response_model=RemediationOut, dependencies=[_rl])
def rollback(
    ref: str, payload: ApprovalIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.INCIDENT_COMMANDER)),
) -> RemediationOut:
    action = _get(db, ref)
    executor.rollback(db, action, actor=user.email)
    audit.record(db, actor=user.email, actor_role=user.role, action="remediation.rollback",
                 resource_type="remediation", resource_id=action.ref, note=payload.reason)
    db.refresh(action)
    return remediation_out(action)
