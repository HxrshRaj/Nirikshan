"""The Python SDK talking to the real FastAPI app (schema, auth, rate limit, query)."""

import pytest

pytestmark = pytest.mark.e2e

sdk = pytest.importorskip("nirikshan_sdk")


def _bridge(api_client, extra_headers=None):
    """SDK transport that delivers through the in-process app (real routing, validation and DB)."""

    def send(body: bytes, headers: dict):
        h = {**headers, **(extra_headers or {})}
        r = api_client.post("/api/telemetry/logs", content=body, headers=h)
        return r.status_code, dict(r.headers), r.content

    return send


def _client(api_client, **kw):
    return sdk.Client(
        "http://testserver/api/telemetry/logs",
        "sdk-e2e",
        send=_bridge(api_client),
        install_hooks=False,
        flush_interval=0.05,
        backoff_base=0.01,
        **kw,
    )


def _crash():
    return {}["missing"]


def test_sdk_error_is_accepted_stored_and_searchable(api_client, auth_headers):
    c = _client(api_client, release="2.0.1", environment="production")
    try:
        try:
            _crash()
        except KeyError as e:
            c.capture_exception(e)
        assert c.flush(5)
        assert c.transport.stats["sent"] == 1 and c.transport.stats["dropped_rejected"] == 0
    finally:
        c.close(1.0)

    r = api_client.get("/api/logs", params={"service": "sdk-e2e", "level": "ERROR"}, headers=auth_headers())
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    attrs = items[0]["attributes"]
    assert attrs["exception"]["type"] == "KeyError"
    assert attrs["exception"]["frames"][-1]["function"] == "_crash"
    assert attrs["release"] == "2.0.1" and len(attrs["fingerprint"]) == 16
    assert attrs["sdk"]["name"] == "nirikshan-sdk-python"


def test_sdk_batch_of_messages_all_accepted(api_client, auth_headers):
    c = _client(api_client)
    try:
        for i in range(25):
            c.capture_message(f"checkout step {i}", level="info")
        assert c.flush(5)
        assert c.transport.stats["sent"] == 25
    finally:
        c.close(1.0)
    r = api_client.get("/api/logs", params={"service": "sdk-e2e", "limit": 100}, headers=auth_headers())
    assert r.json()["total"] == 25


def test_ingest_token_is_enforced_and_sdk_does_not_retry_a_401(api_client, monkeypatch):
    from nirikshan.core.config import get_settings

    monkeypatch.setenv("NIRIKSHAN_INGEST_TOKEN", "s3cr3t-token")
    get_settings.cache_clear()
    try:
        bad = _client(api_client, ingest_token="wrong")
        bad.capture_message("nope")
        assert bad.flush(5)
        assert bad.transport.stats["dropped_rejected"] == 1 and bad.transport.stats["retries"] == 0
        bad.close(1.0)

        good = _client(api_client, ingest_token="s3cr3t-token")
        good.capture_message("yes")
        assert good.flush(5)
        assert good.transport.stats["sent"] == 1
        good.close(1.0)
    finally:
        get_settings.cache_clear()


def test_rate_limited_response_carries_retry_after_header(api_client, monkeypatch):
    from nirikshan.security.ratelimit import RateLimit

    # the limiter is bound at import time, so force a denial for it directly
    monkeypatch.setattr(RateLimit, "check", lambda self, key: (False, 0, 12))
    r = api_client.post("/api/telemetry/logs", json={"logs": [{"service": "rl", "message": "x"}]})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "12"
    assert r.json()["details"]["retry_after_seconds"] == 12


def test_sdk_backs_off_for_the_server_provided_retry_after(api_client, monkeypatch):
    import time

    from nirikshan.security.ratelimit import RateLimit

    calls = {"n": 0}

    def check(self, key):
        calls["n"] += 1
        return (calls["n"] > 1, 0, 1)  # deny the first request only, "retry in 1s"

    monkeypatch.setattr(RateLimit, "check", check)
    c = _client(api_client)
    try:
        t0 = time.monotonic()
        c.capture_message("throttled once")
        assert c.flush(8)
        assert time.monotonic() - t0 >= 0.9  # waited the server's 1s, not the 10ms backoff
        assert c.transport.stats["retries"] == 1 and c.transport.stats["sent"] == 1
    finally:
        c.close(1.0)
