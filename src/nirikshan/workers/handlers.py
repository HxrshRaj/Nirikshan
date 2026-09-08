"""Event handlers that advance the pipeline: telemetry -> anomaly -> alert ->
incident -> investigation -> (optional) remediation proposal.

Each handler is idempotent and defensive: a handler failure logs and the event
is still acked (with a dead-letter log line) so one poison event cannot wedge
the consumer. PostgreSQL remains the source of truth.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.config import get_settings
from nirikshan.core.logging import get_logger
from nirikshan.detection.alerts import evaluate_all_rules
from nirikshan.detection.anomaly import scan_service
from nirikshan.domain.enums import RemediationMode
from nirikshan.incidents.engine import ingest_alert
from nirikshan.models import Alert, Incident, Service

log = get_logger("workers.handlers")


def _services_by_name(db: Session, names: list[str]) -> list[Service]:
    if not names:
        return []
    return list(db.scalars(select(Service).where(Service.name.in_([n.lower() for n in names]))))


def on_telemetry_received(db: Session, payload: dict) -> None:
    kind = payload.get("kind")
    names = payload.get("services", [])
    if kind == "metrics":
        for svc in _services_by_name(db, names):
            scan_service(db, svc)
    # Any telemetry can move an alert rule; re-evaluate the affected environment.
    fired = evaluate_all_rules(db)
    for alert in fired:
        if alert.incident_id is None:
            ingest_alert(db, alert)
    # also correlate any still-unlinked firing alerts
    for alert in db.scalars(
        select(Alert).where(Alert.state == "FIRING", Alert.incident_id.is_(None))
    ):
        ingest_alert(db, alert)


def on_alert_created(db: Session, payload: dict) -> None:
    alert = db.get(Alert, payload.get("alert_id"))
    if alert and alert.incident_id is None:
        ingest_alert(db, alert)


def on_incident_created(db: Session, payload: dict) -> None:
    """Auto-launch an investigation for a freshly created incident."""
    inc = db.get(Incident, payload.get("incident_id"))
    if inc is None or inc.last_investigation_run_id:
        return
    from nirikshan.ai.investigator import investigate

    try:
        investigate(db, inc, actor="ai:investigator")
    except Exception as exc:
        log.warning("worker.investigation_error", incident=inc.ref, error=str(exc))


def on_investigation_completed(db: Session, payload: dict) -> None:
    """Propose remediation automatically only when the mode is not OBSERVE and
    confidence is adequate. Execution still always needs approval unless the
    policy engine explicitly allows autonomy."""
    settings = get_settings()
    if RemediationMode(settings.remediation_mode) == RemediationMode.OBSERVE:
        return
    if payload.get("is_mock") is False and (payload.get("confidence") or 0) < 0.5:
        return
    inc = db.get(Incident, payload.get("incident_id"))
    if inc is None:
        return
    from nirikshan.remediation.agent import propose_remediation

    try:
        propose_remediation(db, inc, actor="ai:remediation")
    except Exception as exc:
        log.info("worker.remediation_skipped", incident=inc.ref, reason=str(exc))


HANDLERS = {
    "TELEMETRY_RECEIVED": on_telemetry_received,
    "ALERT_CREATED": on_alert_created,
    "INCIDENT_CREATED": on_incident_created,
    "INVESTIGATION_COMPLETED": on_investigation_completed,
}
