import pytest

from nirikshan.core.clock import utcnow
from nirikshan.incidents.memory import archive_incident, similar_incidents
from nirikshan.models import Incident
from tests.helpers import make_service

pytestmark = pytest.mark.unit


def _resolved_incident(db, *, title, root_cause, service="payment-service"):
    svc = make_service(db, service, tier=1)
    inc = Incident(
        ref="INC-" + str(1000 + hash(title) % 9000),
        title=title,
        severity="SEV-2",
        status="CLOSED",
        environment_id=svc.environment_id,
        service_id=svc.id,
        service_name=svc.name,
        detected_at=utcnow(),
        resolved_at=utcnow(),
        summary=f"{title}. Resolution: mitigated.",
        root_cause=root_cause,
        contributing_factors=[],
        recommended_actions=["do the thing"],
        affected_services=[service],
        dedup_key="k",
    )
    db.add(inc)
    db.flush()
    return inc


def test_archive_and_retrieve_similar(db):
    a = _resolved_incident(
        db, title="Payment DB pool exhausted", root_cause="Database connection pool exhaustion"
    )
    _resolved_incident(db, title="Notification queue overload", root_cause="Traffic-driven queue saturation",
                       service="notification-service")
    archive_incident(db, a)
    for inc in db.query(Incident).all():
        if inc.id != a.id:
            archive_incident(db, inc)

    results = similar_incidents(db, query_text="database connection pool exhaustion on payment", k=2)
    assert results
    assert results[0]["root_cause"] == "Database connection pool exhaustion"
    assert results[0]["similarity"] >= results[-1]["similarity"]
    assert "database" in results[0]["tags"]


def test_similar_excludes_self(db):
    a = _resolved_incident(db, title="only one", root_cause="something")
    archive_incident(db, a)
    results = similar_incidents(db, query_text="only one", exclude_incident_id=a.id, k=5)
    assert results == []


def test_similar_empty_store(db):
    assert similar_incidents(db, query_text="anything") == []
