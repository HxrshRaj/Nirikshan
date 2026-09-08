from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, require_role
from nirikshan.api.serializers import deployment_out
from nirikshan.catalog.service import get_or_create_environment, get_service
from nirikshan.core.clock import utcnow
from nirikshan.core.events import EventType, emit
from nirikshan.core.ids import short_token
from nirikshan.domain.enums import Role
from nirikshan.models import Deployment, User
from nirikshan.schemas.catalog import DeploymentIn, DeploymentOut

router = APIRouter(tags=["deployments"])


@router.get("/deployments", response_model=list[DeploymentOut])
def list_deployments(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    service: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DeploymentOut]:
    stmt = select(Deployment).order_by(Deployment.started_at.desc()).limit(limit)
    if service:
        svc = get_service(db, service.lower())
        stmt = stmt.where(Deployment.service_id == svc.id)
    return [deployment_out(d) for d in db.scalars(stmt)]


@router.post("/deployments", response_model=DeploymentOut, status_code=201)
def record_deployment(
    payload: DeploymentIn, db: Session = Depends(get_db), actor: User = Depends(require_role(Role.ENGINEER))
) -> DeploymentOut:
    env = get_or_create_environment(db, payload.environment)
    svc = get_service(db, payload.service.lower(), environment=payload.environment)
    dep = Deployment(
        ref="DEP-" + short_token(6),
        environment_id=env.id,
        service_id=svc.id,
        service_name=svc.name,
        version=payload.version,
        previous_version=payload.previous_version,
        commit_sha=payload.commit_sha,
        change_summary=payload.change_summary,
        started_at=payload.started_at or utcnow(),
        completed_at=payload.completed_at,
        status=payload.status.value,
        triggered_by=payload.triggered_by,
        attributes=payload.attributes,
    )
    db.add(dep)
    db.flush()
    emit(EventType.DEPLOYMENT_RECORDED, {"deployment_ref": dep.ref, "service": svc.name, "version": dep.version})
    return deployment_out(dep)
