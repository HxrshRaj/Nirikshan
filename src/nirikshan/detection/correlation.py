"""Alert -> incident correlation.

Multiple alerts firing close together frequently describe a single incident.
We group a new alert into an existing open incident when they share enough of:

* **service** identity (same service, or a direct dependency edge between them)
* **time proximity** (fired within ``CORRELATION_WINDOW``)
* **environment**

and otherwise open a new incident. This is the deduplication + correlation
mechanism (spec 17, 46): four correlated alerts become one incident, and a
repeat of the same alert fingerprint never spawns a second incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.catalog.graph import load_graph
from nirikshan.core.clock import utcnow
from nirikshan.domain.enums import OPEN_INCIDENT_STATUSES
from nirikshan.models import Alert, Incident, Service

CORRELATION_WINDOW = timedelta(minutes=15)


@dataclass
class CorrelationDecision:
    incident: Incident | None
    reason: str
    is_new: bool


def _related_services(db: Session, service: Service) -> set[str]:
    """service id + its direct upstream/downstream neighbours."""
    g = load_graph(db, service.environment_id)
    ids = {service.id}
    ids |= g.depends_on.get(service.id, set())
    ids |= g.dependents.get(service.id, set())
    return ids


def find_incident_for_alert(db: Session, alert: Alert) -> CorrelationDecision:
    svc = db.get(Service, alert.service_id)
    if svc is None:
        return CorrelationDecision(None, "unknown service", is_new=True)

    # 1. Exact fingerprint already tied to an open incident -> dedupe.
    prior = db.scalar(
        select(Alert)
        .where(
            Alert.fingerprint == alert.fingerprint,
            Alert.incident_id.is_not(None),
            Alert.id != alert.id,
        )
        .order_by(Alert.fired_at.desc())
        .limit(1)
    )
    if prior and prior.incident_id:
        inc = db.get(Incident, prior.incident_id)
        if inc and inc.status in {s.value for s in OPEN_INCIDENT_STATUSES}:
            return CorrelationDecision(inc, "same alert fingerprint on open incident", is_new=False)

    # 2. Open incident on the same or a directly-related service, recently.
    related = _related_services(db, svc)
    since = utcnow() - CORRELATION_WINDOW
    candidates = db.scalars(
        select(Incident)
        .where(
            Incident.environment_id == alert.environment_id,
            Incident.status.in_([s.value for s in OPEN_INCIDENT_STATUSES]),
            Incident.detected_at >= since,
        )
        .order_by(Incident.detected_at.desc())
    )
    for inc in candidates:
        if inc.service_id in related or svc.id == inc.service_id:
            same = "same service" if svc.id == inc.service_id else "dependency-linked service"
            return CorrelationDecision(inc, f"open incident on {same} within window", is_new=False)

    return CorrelationDecision(None, "no correlated incident", is_new=True)


def dedup_key_for(service_name: str, environment_id: str, signal_kind: str) -> str:
    return f"{environment_id}:{service_name}:{signal_kind}".lower()
