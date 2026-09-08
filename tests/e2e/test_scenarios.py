"""Full pipeline: telemetry -> anomaly -> alert -> incident -> RCA -> remediation."""

import pytest

from nirikshan.demo.flow import drive_remediation
from nirikshan.demo.scenarios import run_scenario
from nirikshan.incidents.engine import get_by_ref

pytestmark = pytest.mark.e2e

CASES = [
    ("db-exhaustion", "database_saturation", "payment-service"),
    ("deploy-regression", "deployment_regression", "order-service"),
    ("dependency-failure", "upstream_dependency_failure", "payment-service"),
    ("traffic-spike", "traffic_overload", "notification-service"),
]


@pytest.mark.parametrize("key,expected_category,service", CASES)
def test_scenario_produces_correct_rca(db, key, expected_category, service):
    result = run_scenario(db, key, investigate_incident=True, propose_fix=True)
    assert result.incident_ref, f"{key}: no incident created"
    assert result.anomalies > 0
    assert result.alerts
    assert result.top_hypothesis_category == expected_category
    assert result.category_match is True
    assert result.confidence is not None and result.confidence >= 0.6
    assert result.remediation_ref, f"{key}: no remediation proposed"

    inc = get_by_ref(db, result.incident_ref)
    assert inc.service_name == service
    assert inc.evidence, "RCA must be backed by stored evidence"
    assert inc.hypotheses and inc.hypotheses[0].is_selected
    assert any(e.kind == "rca_generated" for e in inc.events)


def test_normal_scenario_creates_no_incident(db):
    result = run_scenario(db, "normal", investigate_incident=True)
    assert result.incident_ref is None
    assert result.anomalies == 0


def test_full_remediation_loop_resolves_incident(db):
    result = run_scenario(db, "db-exhaustion", investigate_incident=True, propose_fix=True)
    inc = get_by_ref(db, result.incident_ref)
    flow = drive_remediation(db, inc, scenario_key="db-exhaustion")
    assert flow.approved and flow.executed
    assert flow.verified is True
    assert flow.verification["success"] is True
    assert flow.incident_status == "RESOLVED"

    # incident memory should have archived it after resolution -> close
    from nirikshan.incidents.engine import close
    from nirikshan.models import HistoricalIncident

    db.refresh(inc)
    close(db, inc, actor="commander@nirikshan.dev")
    assert db.query(HistoricalIncident).filter_by(incident_id=inc.id).count() == 1


def test_reinvestigation_is_idempotent(db):
    result = run_scenario(db, "db-exhaustion", investigate_incident=True)
    inc = get_by_ref(db, result.incident_ref)
    n_ev_1 = len(inc.evidence)
    summary_1 = inc.summary
    from nirikshan.ai.investigator import investigate

    investigate(db, inc)
    db.refresh(inc)
    assert len(inc.evidence) == n_ev_1  # not duplicated
    assert len({h.rank for h in inc.hypotheses}) == len(inc.hypotheses)
    # the AI-analysis block is replaced, not appended, so the summary stays bounded
    assert inc.summary.count("--- AI analysis ---") == 1
    assert len(inc.summary) <= len(summary_1) + 20
