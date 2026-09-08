from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, rate_limit, require_role
from nirikshan.api.serializers import (
    evidence_out,
    hypothesis_out,
    incident_detail,
    incident_summary,
)
from nirikshan.core.errors import ConflictError, NotFoundError
from nirikshan.domain.enums import IncidentStatus, Role
from nirikshan.incidents import engine
from nirikshan.models import Incident, IncidentEvidence, IncidentHypothesis, User
from nirikshan.schemas.common import Page
from nirikshan.schemas.incidents import (
    AcknowledgeIn,
    EvidenceOut,
    IncidentDetail,
    IncidentEventOut,
    IncidentSummary,
    InvestigateIn,
    RCAOut,
    ResolveIn,
)
from nirikshan.security import audit

router = APIRouter(tags=["incidents"])


def _get(db: Session, ref: str) -> Incident:
    inc = engine.get_by_ref(db, ref)
    if inc is None:
        raise NotFoundError(f"incident {ref} not found")
    return inc


@router.get("/incidents", response_model=Page[IncidentSummary])
def list_incidents(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    status: str | None = None,
    severity: str | None = None,
    service: str | None = None,
    open_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[IncidentSummary]:
    from sqlalchemy import func

    from nirikshan.domain.enums import OPEN_INCIDENT_STATUSES

    stmt = select(Incident).order_by(Incident.detected_at.desc())
    if status:
        stmt = stmt.where(Incident.status == status.upper())
    if open_only:
        stmt = stmt.where(Incident.status.in_([s.value for s in OPEN_INCIDENT_STATUSES]))
    if severity:
        stmt = stmt.where(Incident.severity == severity.upper())
    if service:
        stmt = stmt.where(Incident.service_name == service.lower())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.limit(limit).offset(offset))
    return Page[IncidentSummary](
        items=[incident_summary(i) for i in rows], total=total, limit=limit, offset=offset
    )


@router.get("/incidents/{ref}", response_model=IncidentDetail)
def get_incident(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> IncidentDetail:
    return incident_detail(_get(db, ref))


@router.get("/incidents/{ref}/timeline", response_model=list[IncidentEventOut])
def timeline(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> list[IncidentEventOut]:
    inc = _get(db, ref)
    return [
        IncidentEventOut(
            id=e.id, at=e.at, kind=e.kind, message=e.message, actor=e.actor, source=e.source, data=e.data or {}
        )
        for e in sorted(inc.events, key=lambda x: x.at)
    ]


@router.get("/incidents/{ref}/evidence", response_model=list[EvidenceOut])
def evidence(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> list[EvidenceOut]:
    inc = _get(db, ref)
    rows = db.scalars(select(IncidentEvidence).where(IncidentEvidence.incident_id == inc.id))
    return [evidence_out(e) for e in rows]


@router.get("/incidents/{ref}/rca", response_model=RCAOut)
def rca(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> RCAOut:
    inc = _get(db, ref)
    hyps = list(
        db.scalars(
            select(IncidentHypothesis)
            .where(IncidentHypothesis.incident_id == inc.id)
            .order_by(IncidentHypothesis.rank)
        )
    )
    ev = list(db.scalars(select(IncidentEvidence).where(IncidentEvidence.incident_id == inc.id)))
    is_mock = False
    if inc.last_investigation_run_id:
        from nirikshan.models import AgentRun

        run = db.scalar(select(AgentRun).where(AgentRun.run_id == inc.last_investigation_run_id))
        is_mock = bool(run and run.is_mock)
    return RCAOut(
        root_cause=inc.root_cause or "not yet determined",
        confidence=inc.confidence,
        summary=inc.summary,
        contributing_factors=inc.contributing_factors or [],
        recommended_actions=inc.recommended_actions or [],
        affected_services=inc.affected_services or [],
        evidence=[evidence_out(e) for e in ev],
        hypotheses=[hypothesis_out(h) for h in hyps],
        generated_by_run_id=inc.last_investigation_run_id,
        is_mock=is_mock,
    )


@router.post("/incidents/{ref}/acknowledge", response_model=IncidentDetail)
def acknowledge(
    ref: str, payload: AcknowledgeIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.ENGINEER)),
) -> IncidentDetail:
    inc = _get(db, ref)
    engine.acknowledge(db, inc, actor=user.email, note=payload.note)
    audit.record(db, actor=user.email, actor_role=user.role, action="incident.acknowledge",
                 resource_type="incident", resource_id=inc.ref, note=payload.note)
    return incident_detail(inc)


@router.post("/incidents/{ref}/resolve", response_model=IncidentDetail)
def resolve(
    ref: str, payload: ResolveIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.ENGINEER)),
) -> IncidentDetail:
    inc = _get(db, ref)
    engine.resolve(db, inc, actor=user.email, resolution=payload.resolution, root_cause=payload.root_cause)
    audit.record(db, actor=user.email, actor_role=user.role, action="incident.resolve",
                 resource_type="incident", resource_id=inc.ref, note=payload.resolution)
    return incident_detail(inc)


@router.post("/incidents/{ref}/close", response_model=IncidentDetail)
def close(
    ref: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.INCIDENT_COMMANDER))
) -> IncidentDetail:
    inc = _get(db, ref)
    engine.close(db, inc, actor=user.email)
    audit.record(db, actor=user.email, actor_role=user.role, action="incident.close",
                 resource_type="incident", resource_id=inc.ref)
    return incident_detail(inc)


@router.post("/incidents/{ref}/investigate", response_model=IncidentDetail,
             dependencies=[Depends(rate_limit("investigate"))])
def investigate(
    ref: str, payload: InvestigateIn,
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.ENGINEER)),
) -> IncidentDetail:
    inc = _get(db, ref)
    if IncidentStatus(inc.status) in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED) and not payload.force:
        raise ConflictError(f"incident {ref} is {inc.status}; pass force=true to re-investigate")
    from nirikshan.ai.investigator import investigate as run_investigation

    run = run_investigation(db, inc, prompt_version=payload.prompt_version, actor=f"human:{user.email}")
    audit.record(db, actor=user.email, actor_role=user.role, action="incident.investigate",
                 resource_type="incident", resource_id=inc.ref,
                 after={"run_id": run.run_id, "status": run.status})
    db.refresh(inc)
    return incident_detail(inc)
