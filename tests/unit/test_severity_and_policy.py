import pytest

from nirikshan.domain.enums import AlertSeverity, RiskLevel, Role, Severity
from nirikshan.incidents.severity import SeveritySignals, score

pytestmark = pytest.mark.unit


def test_sev1_for_tier1_multi_alert_high_error():
    sev, pts, reasons = score(SeveritySignals(
        service_tier=1, alert_severity=AlertSeverity.CRITICAL, correlated_alerts=4,
        error_rate=0.2, slo_error_rate=0.01, latency_multiple_of_slo=6.0, impacted_user_facing=2,
    ))
    assert sev == Severity.SEV1
    assert pts >= 10


def test_sev4_for_minor_tier3():
    sev, _pts, _r = score(SeveritySignals(
        service_tier=4, alert_severity=AlertSeverity.LOW, correlated_alerts=1,
    ))
    assert sev == Severity.SEV4


def test_policy_blocks_action_not_in_allowlist(db):
    from nirikshan.core.clock import utcnow
    from nirikshan.core.ids import short_token
    from nirikshan.detection.alerts import fingerprint
    from nirikshan.incidents.engine import ingest_alert
    from nirikshan.models import Alert
    from nirikshan.remediation.policy import evaluate
    from tests.helpers import make_service

    svc = make_service(db, "pay", tier=1)
    a = Alert(ref="ALR-" + short_token(6), environment_id=svc.environment_id, service_id=svc.id,
              service_name=svc.name, title="x", signal_kind="error_rate", severity="HIGH",
              state="FIRING", fired_at=utcnow(), fingerprint=fingerprint(svc.name, "error_rate", "", "HIGH"))
    db.add(a); db.flush()
    inc, _ = ingest_alert(db, a)

    decision = evaluate(db, incident=inc, action_name="rm -rf /", parameters={}, risk="LOW",
                        rca_confidence=0.9)
    assert decision.blocked
    assert any(f.code == "invalid_action" for f in decision.findings)


def test_policy_requires_approval_in_default_mode(db):
    from nirikshan.core.clock import utcnow
    from nirikshan.core.ids import short_token
    from nirikshan.detection.alerts import fingerprint
    from nirikshan.incidents.engine import ingest_alert
    from nirikshan.models import Alert
    from nirikshan.remediation.policy import evaluate
    from tests.helpers import make_service

    svc = make_service(db, "pay", tier=1)
    a = Alert(ref="ALR-" + short_token(6), environment_id=svc.environment_id, service_id=svc.id,
              service_name=svc.name, title="x", signal_kind="error_rate", severity="HIGH",
              state="FIRING", fired_at=utcnow(), fingerprint=fingerprint(svc.name, "error_rate", "", "HIGH"))
    db.add(a); db.flush()
    inc, _ = ingest_alert(db, a)

    decision = evaluate(db, incident=inc, action_name="scale_demo_service",
                        parameters={"service": "pay", "replicas_delta": 1}, risk="LOW", rca_confidence=0.9)
    assert decision.requires_approval
    assert not decision.allowed_now
    assert decision.min_role.rank >= Role.INCIDENT_COMMANDER.rank
