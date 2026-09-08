from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, rate_limit, require_role
from nirikshan.api.serializers import alert_out, anomaly_out
from nirikshan.catalog.service import find_service, get_environment
from nirikshan.core.errors import NotFoundError
from nirikshan.domain.enums import Role
from nirikshan.models import Alert, AlertRule, Anomaly, Environment, Service, User
from nirikshan.schemas.alerting import AlertOut, AlertRuleIn, AlertRuleOut, AnomalyOut

router = APIRouter(tags=["alerting"])


def _rule_out(r: AlertRule, db: Session) -> AlertRuleOut:
    svc = db.get(Service, r.service_id) if r.service_id else None
    env = db.get(Environment, r.environment_id)
    return AlertRuleOut(
        id=r.id, name=r.name, description=r.description,
        environment=env.name if env else "production", service=svc.name if svc else None,
        signal_kind=r.signal_kind, subject=r.subject, comparison=r.comparison, threshold=r.threshold,
        for_seconds=r.for_seconds, window_seconds=r.window_seconds, severity=r.severity,
        enabled=r.enabled, labels=r.labels or {}, breaching_since=r.breaching_since,
        last_evaluated_at=r.last_evaluated_at,
    )


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    state: str | None = None,
    service: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AlertOut]:
    stmt = select(Alert).order_by(Alert.fired_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(Alert.state == state.upper())
    if service:
        svc = find_service(db, service.lower())
        stmt = stmt.where(Alert.service_id == (svc.id if svc else "none"))
    return [alert_out(a) for a in db.scalars(stmt)]


@router.get("/alerts/rules", response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db), _u: User = Depends(current_user)) -> list[AlertRuleOut]:
    return [_rule_out(r, db) for r in db.scalars(select(AlertRule).order_by(AlertRule.name))]


@router.post("/alerts/rules", response_model=AlertRuleOut, status_code=201,
             dependencies=[Depends(rate_limit("default"))])
def create_rule(
    payload: AlertRuleIn, db: Session = Depends(get_db), _actor: User = Depends(require_role(Role.ENGINEER))
) -> AlertRuleOut:
    env = get_environment(db, payload.environment)
    svc = find_service(db, payload.service.lower(), environment=payload.environment) if payload.service else None
    rule = AlertRule(
        name=payload.name, description=payload.description, environment_id=env.id,
        service_id=svc.id if svc else None, signal_kind=payload.signal_kind.value,
        subject=payload.subject, comparison=payload.comparison.value, threshold=payload.threshold,
        for_seconds=payload.for_seconds, window_seconds=payload.window_seconds,
        severity=payload.severity.value, enabled=payload.enabled, labels=payload.labels,
    )
    db.add(rule)
    db.flush()
    return _rule_out(rule, db)


@router.get("/alerts/{ref}", response_model=AlertOut)
def get_alert(ref: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> AlertOut:
    a = db.scalar(select(Alert).where(Alert.ref == ref))
    if a is None:
        raise NotFoundError(f"alert {ref} not found")
    return alert_out(a)


@router.get("/anomalies", response_model=list[AnomalyOut])
def list_anomalies(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    service: str | None = None,
    minutes: int = Query(default=180, ge=5, le=1440),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AnomalyOut]:
    from datetime import timedelta

    from nirikshan.core.clock import utcnow

    stmt = (
        select(Anomaly)
        .where(Anomaly.detected_at >= utcnow() - timedelta(minutes=minutes))
        .order_by(Anomaly.detected_at.desc())
        .limit(limit)
    )
    if service:
        svc = find_service(db, service.lower())
        stmt = stmt.where(Anomaly.service_id == (svc.id if svc else "none"))
    return [anomaly_out(a) for a in db.scalars(stmt)]
