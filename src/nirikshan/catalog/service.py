"""CRUD + lookup helpers for the org/environment/service topology."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.errors import ConflictError, NotFoundError
from nirikshan.domain.enums import ServiceHealth
from nirikshan.models import Environment, Organization, Service, ServiceDependency

DEFAULT_ORG = "nirikshan"
DEFAULT_ORG_NAME = "Nirikshan Demo Org"


def get_or_create_org(db: Session, slug: str = DEFAULT_ORG) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        org = Organization(name=DEFAULT_ORG_NAME if slug == DEFAULT_ORG else slug, slug=slug)
        db.add(org)
        db.flush()
    return org


def get_or_create_environment(db: Session, name: str, *, org_slug: str = DEFAULT_ORG) -> Environment:
    org = get_or_create_org(db, org_slug)
    env = db.scalar(
        select(Environment).where(
            Environment.organization_id == org.id, Environment.name == name
        )
    )
    if env is None:
        env = Environment(organization_id=org.id, name=name)
        db.add(env)
        db.flush()
    return env


def get_environment(db: Session, name: str, *, org_slug: str = DEFAULT_ORG) -> Environment:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug))
    if org is None:
        raise NotFoundError(f"organization {org_slug!r} not found")
    env = db.scalar(
        select(Environment).where(
            Environment.organization_id == org.id, Environment.name == name
        )
    )
    if env is None:
        raise NotFoundError(f"environment {name!r} not found")
    return env


def get_service(db: Session, name: str, *, environment: str = "production") -> Service:
    env = get_environment(db, environment)
    svc = db.scalar(
        select(Service).where(Service.environment_id == env.id, Service.name == name)
    )
    if svc is None:
        raise NotFoundError(f"service {name!r} not found in {environment!r}")
    return svc


def find_service(db: Session, name: str, *, environment: str = "production") -> Service | None:
    try:
        return get_service(db, name, environment=environment)
    except NotFoundError:
        return None


def get_or_create_service(
    db: Session,
    name: str,
    *,
    environment: str = "production",
    kind: str = "service",
    tier: int = 2,
    display_name: str = "",
    **extra,
) -> Service:
    env = get_or_create_environment(db, environment)
    svc = db.scalar(
        select(Service).where(Service.environment_id == env.id, Service.name == name)
    )
    if svc is None:
        svc = Service(
            environment_id=env.id,
            name=name,
            display_name=display_name or name.replace("-", " ").title(),
            kind=kind,
            tier=tier,
            health=ServiceHealth.UNKNOWN.value,
            **extra,
        )
        db.add(svc)
        db.flush()
    return svc


def create_service(db: Session, payload) -> Service:
    env = get_or_create_environment(db, payload.environment)
    existing = db.scalar(
        select(Service).where(Service.environment_id == env.id, Service.name == payload.name)
    )
    if existing is not None:
        raise ConflictError(f"service {payload.name!r} already exists in {payload.environment!r}")
    svc = Service(
        environment_id=env.id,
        name=payload.name,
        display_name=payload.display_name or payload.name.replace("-", " ").title(),
        kind=payload.kind,
        tier=payload.tier,
        owner_team=payload.owner_team,
        runbook_url=payload.runbook_url,
        slo_latency_ms_p95=payload.slo_latency_ms_p95,
        slo_error_rate=payload.slo_error_rate,
        attributes=payload.attributes,
        health=ServiceHealth.UNKNOWN.value,
    )
    db.add(svc)
    db.flush()
    return svc


def list_services(db: Session, *, environment: str | None = None) -> list[Service]:
    stmt = select(Service).order_by(Service.tier, Service.name)
    if environment:
        env = get_environment(db, environment)
        stmt = stmt.where(Service.environment_id == env.id)
    return list(db.scalars(stmt))


def set_service_health(db: Session, service: Service, health: ServiceHealth) -> None:
    if service.health != health.value:
        service.health = health.value
    service.health_updated_at = utcnow()
    db.add(service)


def add_dependency(db: Session, payload) -> ServiceDependency:
    up = get_service(db, payload.upstream, environment=payload.environment)
    down = get_service(db, payload.downstream, environment=payload.environment)
    if up.id == down.id:
        raise ConflictError("a service cannot depend on itself")
    existing = db.scalar(
        select(ServiceDependency).where(
            ServiceDependency.upstream_id == up.id,
            ServiceDependency.downstream_id == down.id,
        )
    )
    if existing is not None:
        return existing
    edge = ServiceDependency(
        upstream_id=up.id,
        downstream_id=down.id,
        kind=payload.kind,
        critical=payload.critical,
    )
    db.add(edge)
    db.flush()
    return edge
