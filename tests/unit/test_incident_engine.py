import pytest

from nirikshan.core.clock import utcnow
from nirikshan.core.errors import StateTransitionError
from nirikshan.core.ids import short_token
from nirikshan.detection.alerts import fingerprint
from nirikshan.domain.enums import IncidentStatus
from nirikshan.incidents.engine import ingest_alert, transition
from nirikshan.models import Alert, Incident
from tests.helpers import make_service

pytestmark = pytest.mark.unit


def _alert(db, svc, *, signal="error_rate", severity="HIGH", title="err"):
    a = Alert(
        ref="ALR-" + short_token(6), environment_id=svc.environment_id, service_id=svc.id,
        service_name=svc.name, title=title, signal_kind=signal, subject="", severity=severity,
        state="FIRING", fired_at=utcnow(),
        fingerprint=fingerprint(svc.name, signal, "", severity),
    )
    db.add(a)
    db.flush()
    return a


def test_incident_created_from_alert(db):
    svc = make_service(db, "pay", tier=1)
    inc, created = ingest_alert(db, _alert(db, svc))
    assert created and inc.status == IncidentStatus.DETECTED.value
    assert inc.ref.startswith("INC-")
    assert inc.alert_count == 1
    assert any(e.kind == "incident_detected" for e in inc.events)


def test_second_alert_same_service_correlates_not_new(db):
    svc = make_service(db, "pay", tier=1)
    inc1, _ = ingest_alert(db, _alert(db, svc, signal="error_rate"))
    inc2, created2 = ingest_alert(db, _alert(db, svc, signal="latency", title="lat"))
    assert not created2
    assert inc1.id == inc2.id
    assert inc1.alert_count == 2
    assert db.query(Incident).count() == 1


def test_duplicate_fingerprint_does_not_double_count(db):
    svc = make_service(db, "pay")
    a = _alert(db, svc)
    ingest_alert(db, a)
    ingest_alert(db, a)  # same object again
    inc = db.query(Incident).one()
    assert inc.alert_count == 1


def test_state_machine_rejects_illegal_transition(db):
    svc = make_service(db, "pay")
    inc, _ = ingest_alert(db, _alert(db, svc))
    with pytest.raises(StateTransitionError):
        transition(db, inc, IncidentStatus.CLOSED, actor="x")
        transition(db, inc, IncidentStatus.DETECTED, actor="x")


def test_state_machine_happy_path(db):
    svc = make_service(db, "pay")
    inc, _ = ingest_alert(db, _alert(db, svc))
    transition(db, inc, IncidentStatus.ACKNOWLEDGED, actor="eng@x")
    assert inc.acknowledged_at is not None and inc.acknowledged_by == "eng@x"
    transition(db, inc, IncidentStatus.MITIGATING, actor="eng@x")
    transition(db, inc, IncidentStatus.RESOLVED, actor="eng@x")
    assert inc.resolved_at is not None
    transition(db, inc, IncidentStatus.CLOSED, actor="eng@x")
    assert inc.closed_at is not None
