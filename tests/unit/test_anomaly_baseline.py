import pytest

from nirikshan.detection.anomaly import detect_for_metric, scan_service
from nirikshan.detection.baseline import recompute_baseline
from tests.helpers import make_service, seed_metric_series

pytestmark = pytest.mark.unit


def test_baseline_ignores_recent_window(db):
    svc = make_service(db, "baseline-svc")
    seed_metric_series(db, svc, "request_latency_ms", minutes=200, baseline=120, noise=6,
                       spike_last_minutes=20, spike_multiplier=8.0)
    view = recompute_baseline(db, svc, "request_latency_ms", exclude_last_minutes=25, lookback_minutes=240)
    assert view is not None
    # the 8x spike in the last 20 min must not drag the mean far from 120
    assert 100 < view.mean < 150
    assert view.std < 40


def test_zscore_anomaly_detected_on_sustained_spike(db):
    svc = make_service(db, "anomaly-svc")
    seed_metric_series(db, svc, "error_rate", minutes=200, baseline=0.01, noise=0.002,
                       spike_last_minutes=15, spike_multiplier=12.0)
    result = detect_for_metric(db, svc, "error_rate", window_minutes=20, persist=False)
    assert result is not None
    assert result.direction == "high"
    assert result.score > 3.5
    assert 0.4 <= result.confidence <= 0.99
    assert result.observed_value > result.expected_high


def test_no_anomaly_on_steady_series(db):
    svc = make_service(db, "steady-svc")
    seed_metric_series(db, svc, "cpu_usage", minutes=200, baseline=0.4, noise=0.02)
    assert detect_for_metric(db, svc, "cpu_usage", window_minutes=20, persist=False) is None


def test_single_blip_is_suppressed(db):
    svc = make_service(db, "blip-svc")
    seed_metric_series(db, svc, "queue_depth", minutes=200, baseline=10, noise=1,
                       spike_last_minutes=1, spike_multiplier=20.0)
    # only the final point spikes -> not "sustained" -> no anomaly
    assert detect_for_metric(db, svc, "queue_depth", window_minutes=20, persist=False) is None


def test_scan_service_persists_and_is_idempotentish(db):
    svc = make_service(db, "scan-svc")
    seed_metric_series(db, svc, "request_latency_ms", minutes=200, baseline=100, noise=4,
                       spike_last_minutes=15, spike_multiplier=9.0)
    results = scan_service(db, svc, metrics=["request_latency_ms"])
    assert len(results) == 1
    from nirikshan.models import Anomaly

    assert db.query(Anomaly).count() == 1
