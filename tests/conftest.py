"""Shared pytest fixtures.

By default tests run against an in-memory SQLite database and a ``fakeredis``
client (fast, hermetic - the ``unit`` / ``e2e`` / ``ai_eval`` / ``failure``
markers). Tests marked ``integration`` require real services and are skipped
unless ``NIRIKSHAN_TEST_DATABASE_URL`` (Postgres) is set; CI provides one via a
service container.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NIRIKSHAN_SECRET_KEY", "test-secret")
os.environ.setdefault("NIRIKSHAN_LLM_PROVIDER", "mock")
os.environ.setdefault("NIRIKSHAN_BOOTSTRAP_ADMIN_EMAIL", "admin@nirikshan.dev")
os.environ.setdefault("NIRIKSHAN_BOOTSTRAP_ADMIN_PASSWORD", "admin12345")
os.environ.setdefault("NIRIKSHAN_REMEDIATION_MODE", "APPROVAL_REQUIRED")


def _reset_settings_cache() -> None:
    from nirikshan.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def sqlite_url() -> str:
    return "sqlite+pysqlite:///:memory:"


@pytest.fixture
def fake_redis():
    import fakeredis

    from nirikshan.core import redis_bus

    client = fakeredis.FakeStrictRedis(decode_responses=True)
    redis_bus.set_client(client)
    yield client
    redis_bus.set_client(None)


@pytest.fixture
def settings(sqlite_url, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_DATABASE_URL", sqlite_url)
    _reset_settings_cache()
    from nirikshan.core.config import get_settings

    s = get_settings()
    yield s
    _reset_settings_cache()


@pytest.fixture
def db(settings, fake_redis):
    """A fresh schema + session per test."""
    from nirikshan.core.db import create_all, drop_all, init_engine, reset_engine, session_factory

    reset_engine()
    init_engine(settings)
    create_all()
    session = session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        drop_all()
        reset_engine()


@pytest.fixture
def api_client(settings, fake_redis):
    """FastAPI TestClient with lifespan (schema + bootstrap admin) applied."""
    from fastapi.testclient import TestClient

    from nirikshan.api.app import create_app
    from nirikshan.core.db import drop_all, reset_engine

    reset_engine()
    with TestClient(create_app()) as client:
        yield client
    try:
        drop_all()
    except Exception:
        pass
    reset_engine()


@pytest.fixture
def auth_headers(api_client):
    def _login(email: str = "admin@nirikshan.dev", password: str = "admin12345") -> dict:
        r = api_client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


# --- integration (real services) ---
@pytest.fixture
def pg_url() -> str:
    url = os.environ.get("NIRIKSHAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("integration test: set NIRIKSHAN_TEST_DATABASE_URL to a Postgres DSN")
    return url


@pytest.fixture
def real_redis_url() -> str:
    return os.environ.get("NIRIKSHAN_TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
def pg_db(pg_url, monkeypatch, real_redis_url):
    import redis as _redis

    from nirikshan.core import redis_bus
    from nirikshan.core.db import create_all, drop_all, init_engine, reset_engine, session_factory

    monkeypatch.setenv("NIRIKSHAN_DATABASE_URL", pg_url)
    monkeypatch.setenv("NIRIKSHAN_REDIS_URL", real_redis_url)
    _reset_settings_cache()
    try:
        client = _redis.Redis.from_url(real_redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        client.flushdb()
        redis_bus.set_client(client)
    except Exception:
        pytest.skip("integration test: real Redis not reachable")

    from nirikshan.core.config import get_settings

    reset_engine()
    init_engine(get_settings())
    drop_all()
    create_all()
    session = session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        drop_all()
        reset_engine()
        redis_bus.set_client(None)
        _reset_settings_cache()
