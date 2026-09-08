import pytest

from nirikshan.remediation.verification import run_verification
from tests.helpers import make_service, seed_metric_series

pytestmark = pytest.mark.unit


def test_verification_passes_when_metric_under_target(db):
    svc = make_service(db, "pay", slo_error_rate=0.02, slo_latency_ms_p95=300)
    seed_metric_series(db, svc, "request_latency_ms", minutes=10, baseline=120, noise=5)
    seed_metric_series(db, svc, "request_count", minutes=10, baseline=100, noise=2)
    plan = {
        "checks": [
            {"service": "pay", "metric": "request_latency_ms", "agg": "p95", "op": "lt", "target": 400,
             "window_seconds": 300},
        ],
        "compare_to_baseline": True,
    }
    report = run_verification(db, plan)
    assert report["success"] is True
    assert report["passed"] == report["total"] == 1


def test_verification_fails_when_metric_over_target(db):
    svc = make_service(db, "pay")
    seed_metric_series(db, svc, "database_connections", minutes=10, baseline=95, noise=3)
    plan = {"checks": [{"service": "pay", "metric": "database_connections", "op": "lt", "target": 70,
                        "window_seconds": 300}]}
    report = run_verification(db, plan)
    assert report["success"] is False
    assert report["checks"][0]["ok"] is False


def test_verification_missing_data_is_not_success(db):
    make_service(db, "pay")
    report = run_verification(db, {"checks": [{"service": "pay", "metric": "queue_depth", "op": "lt", "target": 10}]})
    assert report["success"] is False
    assert report["checks"][0]["measured"] is None


def test_ratelimit_allows_then_blocks(db, fake_redis, settings, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_RATELIMIT_DEFAULT", "3/60")
    from nirikshan.core.config import get_settings

    get_settings.cache_clear()
    from nirikshan.security.ratelimit import RateLimit

    rl = RateLimit("default")
    results = [rl.check("user-1")[0] for _ in range(5)]
    assert results[:3] == [True, True, True]
    assert results[3] is False and results[4] is False
    # a different identity is independent
    assert rl.check("user-2")[0] is True


def test_ratelimit_fails_open_without_redis(monkeypatch, settings):
    from nirikshan.core import redis_bus

    redis_bus.set_client(None)
    monkeypatch.setattr(redis_bus, "_injected", False)
    monkeypatch.setattr(redis_bus, "_open_until", 0.0)

    class _Dead:
        def pipeline(self):
            raise redis_bus.redis.RedisError("down")

    monkeypatch.setattr(redis_bus, "_client", _Dead())
    from nirikshan.security.ratelimit import RateLimit

    allowed, remaining, retry = RateLimit("default").check("x")
    assert allowed is True  # fails open
    redis_bus.set_client(None)
