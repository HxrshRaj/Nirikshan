"""Dependency-graph algorithms: traversal, blast radius, upstream root search.

The graph is small (tens of services) so plain in-Python BFS over an adjacency
map loaded once per request is more than sufficient and keeps the logic testable
without a database.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.models import Service, ServiceDependency


@dataclass
class Graph:
    """In-memory view of the dependency graph for one environment."""

    services: dict[str, Service]
    # upstream -> {downstream service ids it calls / depends on}
    depends_on: dict[str, set[str]] = field(default_factory=dict)
    # downstream -> {upstream service ids that call it}
    dependents: dict[str, set[str]] = field(default_factory=dict)
    critical_edges: set[tuple[str, str]] = field(default_factory=set)

    def name(self, sid: str) -> str:
        svc = self.services.get(sid)
        return svc.name if svc else sid

    def id_for(self, name: str) -> str | None:
        for sid, svc in self.services.items():
            if svc.name == name:
                return sid
        return None

    # ---- traversals -----------------------------------------------------
    def downstream_closure(self, sid: str) -> list[str]:
        """Everything ``sid`` transitively depends on."""
        return _bfs(sid, self.depends_on)

    def dependents_closure(self, sid: str) -> list[str]:
        """Everything that transitively depends on ``sid`` (blast radius)."""
        return _bfs(sid, self.dependents)

    def direct_dependents(self, sid: str) -> list[str]:
        return sorted(self.dependents.get(sid, set()))

    def blast_radius(self, sid: str) -> dict:
        direct = self.direct_dependents(sid)
        full = self.dependents_closure(sid)
        indirect = [x for x in full if x not in direct]
        downstream = self.downstream_closure(sid)
        impacted_user_facing = sorted(
            {
                self.name(x)
                for x in full
                if (s := self.services.get(x)) and s.tier == 1
            }
        )
        return {
            "service": self.name(sid),
            "direct_dependents": [self.name(x) for x in direct],
            "indirect_dependents": [self.name(x) for x in indirect],
            "downstream_dependencies": [self.name(x) for x in downstream],
            "impacted_user_facing": impacted_user_facing,
            "total_impacted": len(full),
        }


def _bfs(start: str, adjacency: dict[str, set[str]]) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    q: deque[str] = deque(adjacency.get(start, set()))
    while q:
        node = q.popleft()
        if node in seen or node == start:
            continue
        seen.add(node)
        order.append(node)
        q.extend(adjacency.get(node, set()))
    return order


def load_graph(db: Session, environment_id: str) -> Graph:
    services = {
        s.id: s
        for s in db.scalars(select(Service).where(Service.environment_id == environment_id))
    }
    g = Graph(services=services)
    edges = db.scalars(
        select(ServiceDependency).where(
            ServiceDependency.upstream_id.in_(services.keys())
        )
    )
    for e in edges:
        if e.downstream_id not in services:
            continue
        g.depends_on.setdefault(e.upstream_id, set()).add(e.downstream_id)
        g.dependents.setdefault(e.downstream_id, set()).add(e.upstream_id)
        if e.critical:
            g.critical_edges.add((e.upstream_id, e.downstream_id))
    return g


def rank_probable_root(g: Graph, impacted_service_ids: list[str]) -> list[str]:
    """Given a set of impacted services, rank which is the most likely origin.

    Heuristic: a service that many other impacted services (transitively) depend
    on is a better root-cause candidate than a leaf that only depends on others.
    """
    impacted = set(impacted_service_ids)
    scored: list[tuple[float, str]] = []
    for sid in impacted:
        downstream = set(g.downstream_closure(sid))
        # how many impacted services sit "above" this one
        covers = len(impacted & set(g.dependents_closure(sid)))
        # penalise services that themselves depend on other impacted services
        depends_on_impacted = len(impacted & downstream)
        score = covers - 0.5 * depends_on_impacted
        scored.append((score, sid))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [sid for _, sid in scored]
