"""Incident lifecycle engine.

Responsibilities
----------------
* Turn correlated alerts into incidents (create or attach) with deduplication.
* Enforce the incident state machine (``INCIDENT_TRANSITIONS``).
* Maintain the timeline (``incident_events``) from real, stored facts.
* Compute severity and blast radius on create / escalation.
* Emit ``INCIDENT_CREATED`` / ``INCIDENT_UPDATED`` for the workers + SSE.

PostgreSQL is authoritative here. All state changes happen inside the caller's
transaction; events are emitted after ``flush`` so ids are populated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.catalog.graph import load_graph
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import StateTransitionError
from nirikshan.core.events import EventType, emit
from nirikshan.core.logging import get_logger
from nirikshan.detection.correlation import dedup_key_for, find_incident_for_alert
from nirikshan.domain.enums import (
    INCIDENT_TRANSITIONS,
    AlertSeverity,
    IncidentStatus,
    Severity,
)
from nirikshan.incidents.severity import SeveritySignals, score
from nirikshan.models import Alert, Incident, IncidentEvent, Service
from nirikshan.telemetry.aggregate import compute_service_health

log = get_logger("incidents.engine")

_NEXT_INCIDENT_SEQ = "incident-seq"


def _incident_ref(db: Session) -> str:
    n = db.scalar(select(Incident).order_by(Incident.created_at.desc()).limit(1))
    base = 1000
    if n and n.ref.startswith("INC-") and n.ref[4:].isdigit():
        base = int(n.ref[4:])
    return f"INC-{base + 1}"


def add_event(
    db: Session,
    incident: Incident,
    *,
    kind: str,
    message: str,
    actor: str = "system",
    source: str = "system",
    at: datetime | None = None,
    data: dict | None = None,
) -> IncidentEvent:
    ev = IncidentEvent(
        incident_id=incident.id,
        at=at or utcnow(),
        kind=kind,
        message=message,
        actor=actor,
        source=source,
        data=data or {},
    )
    db.add(ev)
    db.flush()
    return ev


def _blast_radius(db: Session, service: Service) -> dict:
    g = load_graph(db, service.environment_id)
    return g.blast_radius(service.id)


def _severity_for(db: Session, service: Service, alerts: list[Alert]) -> tuple[Severity, float, list[str]]:
    health = compute_service_health(db, service)
    worst_alert = AlertSeverity.LOW
    for lvl in (AlertSeverity.CRITICAL, AlertSeverity.HIGH, AlertSeverity.MEDIUM, AlertSeverity.LOW):
        if any(a.severity == lvl.value for a in alerts):
            worst_alert = lvl
            break
    br = _blast_radius(db, service)
    latency_mult = None
    if health.latency_p95_ms and service.slo_latency_ms_p95:
        latency_mult = health.latency_p95_ms / service.slo_latency_ms_p95
    dependency_outage = any(a.signal_kind == "service_health" for a in alerts) and health.error_rate is None
    sig = SeveritySignals(
        service_tier=service.tier,
        alert_severity=worst_alert,
        correlated_alerts=len(alerts),
        error_rate=health.error_rate,
        slo_error_rate=service.slo_error_rate,
        latency_multiple_of_slo=latency_mult,
        impacted_user_facing=len(br.get("impacted_user_facing", [])),
        dependency_outage=dependency_outage,
    )
    return score(sig)


def _title(service: Service, alert: Alert, severity: Severity) -> str:
    kind = alert.signal_kind.replace("_", " ")
    return f"{service.display_name or service.name} {kind} degradation"


def ingest_alert(db: Session, alert: Alert) -> tuple[Incident, bool]:
    """Correlate an alert into an incident. Returns ``(incident, created)``."""
    decision = find_incident_for_alert(db, alert)
    service = db.get(Service, alert.service_id)
    assert service is not None

    if decision.incident is not None:
        inc = decision.incident
        _attach_alert(db, inc, alert, reason=decision.reason)
        return inc, False

    severity, points, reasons = _severity_for(db, service, [alert])
    now = utcnow()
    inc = Incident(
        ref=_incident_ref(db),
        title=_title(service, alert, severity),
        severity=severity.value,
        status=IncidentStatus.DETECTED.value,
        environment_id=alert.environment_id,
        service_id=service.id,
        service_name=service.name,
        detected_at=alert.fired_at or now,
        summary=(
            f"Detected from alert {alert.ref} ({alert.title}). "
            f"Severity {severity.value} (score {points}): {'; '.join(reasons) or 'baseline signals'}."
        ),
        dedup_key=dedup_key_for(service.name, alert.environment_id, alert.signal_kind),
        alert_count=1,
        correlated_alert_refs=[alert.ref],
        blast_radius=_blast_radius(db, service),
        affected_services=[service.name],
    )
    inc.affected_services = sorted(
        {service.name, *inc.blast_radius.get("direct_dependents", [])}
    )
    db.add(inc)
    db.flush()

    alert.incident_id = inc.id
    db.add(alert)

    add_event(
        db, inc, kind="incident_detected",
        message=f"Incident opened from alert {alert.ref}: {alert.title}",
        at=inc.detected_at, data={"alert_ref": alert.ref, "severity_score": points, "reasons": reasons},
    )
    add_event(
        db, inc, kind="alert_correlated",
        message=f"Alert {alert.ref} correlated ({decision.reason})",
        data={"alert_ref": alert.ref},
    )
    emit(
        EventType.INCIDENT_CREATED,
        {
            "incident_id": inc.id,
            "incident_ref": inc.ref,
            "service": service.name,
            "severity": inc.severity,
            "environment_id": inc.environment_id,
            "title": inc.title,
        },
    )
    log.info("incident.created", ref=inc.ref, service=service.name, severity=inc.severity)
    return inc, True


def _attach_alert(db: Session, inc: Incident, alert: Alert, *, reason: str) -> None:
    if alert.ref in (inc.correlated_alert_refs or []):
        alert.incident_id = inc.id
        db.add(alert)
        return
    alert.incident_id = inc.id
    db.add(alert)
    inc.alert_count = (inc.alert_count or 0) + 1
    inc.correlated_alert_refs = sorted({*(inc.correlated_alert_refs or []), alert.ref})

    service = db.get(Service, inc.service_id)
    linked_alerts = list(
        db.scalars(select(Alert).where(Alert.incident_id == inc.id))
    )
    new_sev, points, reasons = _severity_for(db, service, linked_alerts)
    escalated = Severity(new_sev).rank < Severity(inc.severity).rank
    if escalated:
        old = inc.severity
        inc.severity = new_sev.value
        add_event(
            db, inc, kind="severity_escalated",
            message=f"Severity escalated {old} -> {new_sev.value} (score {points})",
            data={"reasons": reasons},
        )
    add_event(
        db, inc, kind="alert_correlated",
        message=f"Alert {alert.ref} correlated into {inc.ref} ({reason})",
        data={"alert_ref": alert.ref, "alert_count": inc.alert_count},
    )
    db.add(inc)
    db.flush()
    emit(
        EventType.INCIDENT_UPDATED,
        {
            "incident_id": inc.id,
            "incident_ref": inc.ref,
            "change": "alert_correlated",
            "alert_count": inc.alert_count,
            "severity": inc.severity,
        },
    )


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def transition(
    db: Session,
    incident: Incident,
    to_status: IncidentStatus,
    *,
    actor: str = "system",
    source: str = "system",
    note: str = "",
) -> Incident:
    current = IncidentStatus(incident.status)
    if to_status == current:
        return incident
    allowed = INCIDENT_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        raise StateTransitionError(
            f"cannot move incident {incident.ref} from {current.value} to {to_status.value}",
            details={"allowed": sorted(s.value for s in allowed)},
        )
    now = utcnow()
    incident.status = to_status.value
    if to_status == IncidentStatus.ACKNOWLEDGED and not incident.acknowledged_at:
        incident.acknowledged_at = now
        incident.acknowledged_by = actor
    if to_status == IncidentStatus.MITIGATING and not incident.mitigated_at:
        incident.mitigated_at = now
    if to_status == IncidentStatus.RESOLVED and not incident.resolved_at:
        incident.resolved_at = now
        incident.resolved_by = actor
    if to_status == IncidentStatus.CLOSED and not incident.closed_at:
        incident.closed_at = now
    db.add(incident)
    add_event(
        db, incident, kind="status_changed",
        message=f"Status {current.value} -> {to_status.value}" + (f": {note}" if note else ""),
        actor=actor, source=source, data={"from": current.value, "to": to_status.value},
    )
    db.flush()
    emit(
        EventType.INCIDENT_UPDATED,
        {"incident_id": incident.id, "incident_ref": incident.ref, "change": "status", "status": to_status.value},
    )
    return incident


def acknowledge(db: Session, incident: Incident, *, actor: str, note: str = "") -> Incident:
    return transition(
        db, incident, IncidentStatus.ACKNOWLEDGED, actor=actor, source="human", note=note
    )


def start_investigation_state(db: Session, incident: Incident) -> None:
    if IncidentStatus(incident.status) == IncidentStatus.DETECTED:
        try:
            transition(db, incident, IncidentStatus.INVESTIGATING, actor="ai:investigator", source="ai")
        except StateTransitionError:
            pass


def resolve(
    db: Session, incident: Incident, *, actor: str, resolution: str = "", root_cause: str = ""
) -> Incident:
    if root_cause:
        incident.root_cause = root_cause
    if resolution:
        incident.summary = (incident.summary + "\n\nResolution: " + resolution).strip()
    inc = transition(
        db, incident, IncidentStatus.RESOLVED, actor=actor, source="human", note=resolution
    )
    # resolve any still-firing alerts tied to the incident
    from nirikshan.domain.enums import AlertState

    for a in db.scalars(select(Alert).where(Alert.incident_id == inc.id)):
        if a.state == AlertState.FIRING.value:
            a.state = AlertState.RESOLVED.value
            a.resolved_at = utcnow()
            db.add(a)
    return inc


def close(db: Session, incident: Incident, *, actor: str) -> Incident:
    inc = transition(db, incident, IncidentStatus.CLOSED, actor=actor, source="human")
    from nirikshan.incidents.memory import archive_incident

    archive_incident(db, inc)
    return inc


def get_by_ref(db: Session, ref: str) -> Incident | None:
    return db.scalar(select(Incident).where(Incident.ref == ref))
