import pytest

from nirikshan.core import clock
from nirikshan.core.clock import utcnow
from nirikshan.detection.alerts import evaluate_rule, fingerprint
from nirikshan.domain.enums import AlertSignalKind, ComparisonOp
from nirikshan.models import Alert, AlertRule
from tests.helpers import make_service, seed_metric_series

pytestmark = pytest.mark.unit


def _rule(db, svc, **kw):
    defaults = dict(
        name="test-rule", environment_id=svc.environment_id, service_id=svc.id,
        signal_kind=AlertSignalKind.RESOURCE.value, subject="database_connections",
        comparison=ComparisonOp.GT.value, threshold=80.0, for_seconds=120, window_seconds=300,
        severity="HIGH", enabled=True,
    )
    defaults.update(kw)
    r = AlertRule(**defaults)
    db.add(r)
    db.flush()
    return r


def test_rule_fires_after_dwell_and_is_deduped(db):
    svc = make_service(db, "alert-svc")
    seed_metric_series(db, svc, "database_connections", minutes=60, baseline=40, noise=3,
                       spike_last_minutes=20, spike_multiplier=3.0)  # ~120 for 20 min
    rule = _rule(db, svc)

    a1 = evaluate_rule(db, rule)
    assert a1 is not None and a1.state == "FIRING"
    assert a1.fingerprint == fingerprint(svc.name, rule.signal_kind, rule.subject, rule.severity)

    a2 = evaluate_rule(db, rule)  # second pass must not create a new alert
    assert db.query(Alert).count() == 1
    assert a2.id == a1.id


def test_rule_does_not_fire_below_threshold(db):
    svc = make_service(db, "quiet-svc")
    seed_metric_series(db, svc, "database_connections", minutes=60, baseline=30, noise=2)
    rule = _rule(db, svc, for_seconds=0)
    assert evaluate_rule(db, rule) is None
    assert db.query(Alert).count() == 0


def test_rule_resolves_when_condition_clears(db):
    svc = make_service(db, "recover-svc")
    seed_metric_series(db, svc, "database_connections", minutes=60, baseline=40, noise=3,
                       spike_last_minutes=30, spike_multiplier=3.0)
    rule = _rule(db, svc)
    alert = evaluate_rule(db, rule)
    assert alert.state == "FIRING"

    # advance the clock past the spike window so the recent window is all-clear
    clock.freeze(utcnow())
    try:
        # wipe recent metrics and add low values
        from nirikshan.models import TelemetryMetric
        db.query(TelemetryMetric).delete()
        seed_metric_series(db, svc, "database_connections", minutes=30, baseline=30, noise=2)
        evaluate_rule(db, rule)
        db.flush()
    finally:
        clock.unfreeze()
    db.refresh(alert)
    assert alert.state == "RESOLVED"
    assert alert.resolved_at is not None
