from datetime import timedelta

import pytest

from nirikshan.core.clock import utcnow
from nirikshan.core.errors import NotFoundError
from nirikshan.models import TelemetryLog
from nirikshan.telemetry.query import get_trace, metric_series, search_logs
from tests.helpers import make_service, seed_metric_series

pytestmark = pytest.mark.unit


def _log(db, svc, level, msg, *, trace_id=None, minutes_ago=1):
    db.add(
        TelemetryLog(
            ts=utcnow() - timedelta(minutes=minutes_ago),
            ingested_at=utcnow(),
            environment_id=svc.environment_id,
            service_id=svc.id,
            service_name=svc.name,
            level=level,
            message=msg,
            trace_id=trace_id,
            attributes={},
        )
    )
    db.flush()


def test_log_search_filters(db):
    svc = make_service(db, "logs-svc")
    _log(db, svc, "INFO", "started up")
    _log(db, svc, "ERROR", "boom: connection refused", trace_id="trc_abc")
    _log(db, svc, "WARN", "slow query")

    rows, total = search_logs(db, service="logs-svc", minutes=60)
    assert total == 3

    rows, total = search_logs(db, service="logs-svc", level="ERROR", minutes=60)
    assert total == 1 and rows[0].level == "ERROR"

    rows, total = search_logs(db, service="logs-svc", min_level="WARN", minutes=60)
    assert total == 2  # WARN + ERROR

    rows, total = search_logs(db, service="logs-svc", query="connection", minutes=60)
    assert total == 1

    rows, total = search_logs(db, service="logs-svc", trace_id="trc_abc", minutes=60)
    assert total == 1


def test_log_search_unknown_service_returns_empty(db):
    make_service(db, "known")
    rows, total = search_logs(db, service="ghost", minutes=60)
    assert rows == [] and total == 0


def test_metric_series_aggregations(db):
    svc = make_service(db, "metric-svc")
    seed_metric_series(db, svc, "request_latency_ms", minutes=30, baseline=100, noise=10)

    avg = metric_series(db, service="metric-svc", metric_name="request_latency_ms", minutes=30, aggregation="avg")
    mx = metric_series(db, service="metric-svc", metric_name="request_latency_ms", minutes=30, aggregation="max")
    p95 = metric_series(db, service="metric-svc", metric_name="request_latency_ms", minutes=30, aggregation="p95")
    assert avg.points and mx.points and p95.points
    assert max(p.value for p in mx.points) >= max(p.value for p in avg.points)


def test_metric_series_unknown_aggregation_raises(db):
    make_service(db, "m2")
    with pytest.raises(NotFoundError):
        metric_series(db, service="m2", metric_name="x", aggregation="median")


def test_get_trace_not_found(db):
    with pytest.raises(NotFoundError):
        get_trace(db, "trc_missing")
