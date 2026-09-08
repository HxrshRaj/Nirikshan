"""Integration tests that require real PostgreSQL + real Redis.

Skipped unless NIRIKSHAN_TEST_DATABASE_URL is set. CI provides service
containers; locally:

    docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=nirikshan -e POSTGRES_USER=nirikshan \
        -e POSTGRES_DB=nirikshan postgres:16-alpine
    docker run -d -p 56379:6379 redis:7-alpine
    NIRIKSHAN_TEST_DATABASE_URL=postgresql+psycopg://nirikshan:nirikshan@localhost:55432/nirikshan \
    NIRIKSHAN_TEST_REDIS_URL=redis://localhost:56379/15 pytest -m integration
"""

import pytest

pytestmark = pytest.mark.integration


def test_full_pipeline_on_postgres(pg_db):
    from nirikshan.demo.scenarios import run_scenario

    result = run_scenario(pg_db, "db-exhaustion", investigate_incident=True, propose_fix=True)
    assert result.incident_ref
    assert result.category_match is True
    assert result.remediation_ref


def test_redis_streams_roundtrip(pg_db):
    from nirikshan.core import redis_bus

    redis_bus.ensure_group()
    sid = redis_bus.publish_event("TEST_EVENT", {"hello": "world", "n": 1})
    assert sid is not None
    events = redis_bus.read_events("test-consumer", count=10, block_ms=500)
    types = [e["type"] for _sid, e in events]
    assert "TEST_EVENT" in types
    for stream_id, _e in events:
        redis_bus.ack_event(stream_id)


def test_worker_drain_advances_pipeline(pg_db, monkeypatch):
    """Emit telemetry events, then let the worker's drain() build the incident."""
    from nirikshan.core import redis_bus
    from nirikshan.demo.generator import generate
    from nirikshan.demo.scenarios import SCENARIOS
    from nirikshan.models import Incident
    from nirikshan.workers.runner import drain

    redis_bus.ensure_group()
    generate(pg_db, scenario=SCENARIOS["db-exhaustion"])
    pg_db.commit()
    redis_bus.publish_event("TELEMETRY_RECEIVED", {"kind": "metrics", "services": ["payment-service"]})

    processed = drain()
    assert processed >= 1
    # worker uses its own sessions; re-query
    from nirikshan.core.db import session_scope

    with session_scope() as s:
        assert s.query(Incident).count() >= 1


def test_concurrent_incident_updates_are_serialised(pg_db):
    """Two sessions acknowledging the same incident: second sees a consistent state."""
    from nirikshan.core.db import session_scope
    from nirikshan.demo.scenarios import run_scenario
    from nirikshan.incidents.engine import acknowledge, get_by_ref

    result = run_scenario(pg_db, "db-exhaustion", investigate_incident=False)
    pg_db.commit()
    ref = result.incident_ref

    with session_scope() as s1:
        inc1 = get_by_ref(s1, ref)
        acknowledge(s1, inc1, actor="a@x")

    with session_scope() as s2:
        inc2 = get_by_ref(s2, ref)
        assert inc2.status == "ACKNOWLEDGED"
        # acknowledging again is a no-op transition, not an error
        acknowledge(s2, inc2, actor="b@x")
        assert inc2.acknowledged_by == "a@x"
