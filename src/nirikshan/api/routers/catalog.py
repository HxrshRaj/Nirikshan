from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, require_role
from nirikshan.api.serializers import service_out
from nirikshan.catalog import service as catalog
from nirikshan.catalog.graph import load_graph
from nirikshan.domain.enums import Role
from nirikshan.models import User
from nirikshan.schemas.catalog import (
    BlastRadius,
    DependencyEdge,
    DependencyGraph,
    DependencyIn,
    ServiceIn,
    ServiceOut,
)
from nirikshan.schemas.common import OkResponse
from nirikshan.security import audit
from nirikshan.telemetry.aggregate import compute_service_health

router = APIRouter(tags=["catalog"])


def _neighbours(db: Session, svc) -> tuple[list[str], list[str]]:
    g = load_graph(db, svc.environment_id)
    return (
        sorted(g.name(x) for x in g.depends_on.get(svc.id, set())),
        sorted(g.name(x) for x in g.dependents.get(svc.id, set())),
    )


@router.get("/services", response_model=list[ServiceOut])
def list_services(
    db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> list[ServiceOut]:
    out = []
    for svc in catalog.list_services(db, environment=environment):
        deps, ups = _neighbours(db, svc)
        out.append(service_out(svc, depends_on=deps, upstream_of=ups))
    return out


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(
    payload: ServiceIn, db: Session = Depends(get_db), actor: User = Depends(require_role(Role.ADMIN))
) -> ServiceOut:
    svc = catalog.create_service(db, payload)
    audit.record(db, actor=actor.email, actor_role=actor.role, action="service.create",
                 resource_type="service", resource_id=svc.id, after={"name": svc.name})
    return service_out(svc)


@router.get("/services/{name}", response_model=ServiceOut)
def get_service(
    name: str, db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> ServiceOut:
    svc = catalog.get_service(db, name.lower(), environment=environment)
    deps, ups = _neighbours(db, svc)
    return service_out(svc, depends_on=deps, upstream_of=ups)


@router.get("/services/{name}/health")
def service_health(
    name: str, db: Session = Depends(get_db), _u: User = Depends(current_user),
    environment: str = "production", window_seconds: int = 600,
) -> dict:
    svc = catalog.get_service(db, name.lower(), environment=environment)
    return compute_service_health(db, svc, window_seconds=window_seconds).as_dict()


@router.get("/dependencies", response_model=DependencyGraph)
def dependency_graph(
    db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> DependencyGraph:
    env = catalog.get_environment(db, environment)
    g = load_graph(db, env.id)
    nodes = []
    for sid, svc in g.services.items():
        nodes.append(
            service_out(
                svc,
                depends_on=sorted(g.name(x) for x in g.depends_on.get(sid, set())),
                upstream_of=sorted(g.name(x) for x in g.dependents.get(sid, set())),
            )
        )
    edges = [
        DependencyEdge(
            upstream=g.name(u), downstream=g.name(d), kind="sync", critical=(u, d) in g.critical_edges
        )
        for u, downs in g.depends_on.items()
        for d in downs
    ]
    return DependencyGraph(nodes=nodes, edges=edges)


@router.post("/dependencies", response_model=OkResponse, status_code=201)
def add_dependency(
    payload: DependencyIn, db: Session = Depends(get_db), actor: User = Depends(require_role(Role.ADMIN))
) -> OkResponse:
    edge = catalog.add_dependency(db, payload)
    audit.record(db, actor=actor.email, actor_role=actor.role, action="dependency.create",
                 resource_type="service_dependency", resource_id=edge.id,
                 after={"upstream": payload.upstream, "downstream": payload.downstream})
    return OkResponse(detail=f"{payload.upstream} -> {payload.downstream}")


@router.get("/services/{name}/blast-radius", response_model=BlastRadius)
def blast_radius(
    name: str, db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> BlastRadius:
    svc = catalog.get_service(db, name.lower(), environment=environment)
    g = load_graph(db, svc.environment_id)
    return BlastRadius(**g.blast_radius(svc.id))


@router.get("/service-map")
def service_map(
    db: Session = Depends(get_db), _u: User = Depends(current_user), environment: str = "production"
) -> dict:
    """Graph + live health + open-incident count per node, for the Service Map UI."""
    from sqlalchemy import func, select

    from nirikshan.domain.enums import OPEN_INCIDENT_STATUSES
    from nirikshan.models import Incident

    env = catalog.get_environment(db, environment)
    g = load_graph(db, env.id)
    open_counts = dict(
        db.execute(
            select(Incident.service_id, func.count())
            .where(Incident.status.in_([s.value for s in OPEN_INCIDENT_STATUSES]))
            .group_by(Incident.service_id)
        ).all()
    )
    nodes = []
    for sid, svc in g.services.items():
        snap = compute_service_health(db, svc)
        nodes.append(
            {
                "id": svc.name,
                "display_name": svc.display_name,
                "kind": svc.kind,
                "tier": svc.tier,
                "health": snap.health.value,
                "error_rate": snap.error_rate,
                "latency_p95_ms": snap.latency_p95_ms,
                "open_incidents": int(open_counts.get(sid, 0)),
                "depends_on": sorted(g.name(x) for x in g.depends_on.get(sid, set())),
            }
        )
    edges = [
        {"source": g.name(u), "target": g.name(d), "critical": (u, d) in g.critical_edges}
        for u, downs in g.depends_on.items()
        for d in downs
    ]
    return {"nodes": nodes, "edges": edges}
