import pytest

from nirikshan.schemas.telemetry import LogIn, MetricIn
from nirikshan.telemetry.ingest import ingest_logs, ingest_metrics

pytestmark = pytest.mark.unit


def test_ingest_metrics_auto_registers_service(db):
    res = ingest_metrics(db, [MetricIn(service="new-svc", metric_name="cpu_usage", value=0.5)])
    assert res.accepted == 1 and res.rejected == 0
    from nirikshan.catalog.service import find_service

    assert find_service(db, "new-svc") is not None


def test_ingest_rejects_non_finite_metric():
    with pytest.raises(Exception):
        MetricIn(service="s", metric_name="m", value=float("inf"))


def test_ingest_logs_partial_batch_survives_bad_row(db):
    good = LogIn(service="svc", level="ERROR", message="ok")
    res = ingest_logs(db, [good, good])
    assert res.accepted == 2

    # a message that is only whitespace is rejected by the schema before it reaches ingest
    with pytest.raises(Exception):
        LogIn(service="svc", level="ERROR", message="   ")


def test_future_timestamp_is_clamped(db):
    from datetime import timedelta

    from nirikshan.core.clock import utcnow

    far_future = utcnow() + timedelta(days=3)
    res = ingest_metrics(db, [MetricIn(service="svc", metric_name="cpu_usage", value=1.0, timestamp=far_future)])
    assert res.accepted == 1
    from nirikshan.models import TelemetryMetric

    row = db.query(TelemetryMetric).one()
    assert row.ts <= utcnow() + timedelta(minutes=6)
