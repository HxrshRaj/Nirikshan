"""Deployment-support behaviour: DB-URL normalisation + in-process worker."""

import time

import pytest

from nirikshan.core.config import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite+pysqlite:///./x.sqlite3", "sqlite+pysqlite:///./x.sqlite3"),
    ],
)
def test_database_url_normalisation(raw, expected):
    assert Settings(database_url=raw).database_url == expected


def test_in_process_worker_starts_drains_and_stops(db, fake_redis, settings):
    """With the flag on, the API lifespan-style thread consumes real events."""
    from nirikshan.core.events import EventType, emit
    from nirikshan.core.redis_bus import ensure_group
    from nirikshan.workers import runner

    ensure_group()
    assert runner.start_in_process() is True
    assert runner.start_in_process() is False  # idempotent

    try:
        # emit an event the worker knows how to handle; it should ack it
        emit(EventType.TELEMETRY_RECEIVED, {"kind": "metrics", "count": 1, "services": []})
        deadline = time.time() + 5
        seen_pending = None
        from nirikshan.core.redis_bus import CONSUMER_GROUP, EVENT_STREAM, get_client

        while time.time() < deadline:
            info = get_client().xpending(EVENT_STREAM, CONSUMER_GROUP)
            seen_pending = info["pending"] if isinstance(info, dict) else info[0]
            if seen_pending == 0:
                break
            time.sleep(0.2)
        assert seen_pending == 0, "worker thread did not consume + ack the event"
    finally:
        runner.stop_in_process(timeout=3)

    assert runner._thread is None
