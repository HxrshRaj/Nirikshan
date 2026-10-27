import json
import time

from nirikshan_sdk.transport import Transport, parse_retry_after


def test_batches_events_into_one_request(server, make_client):
    c = make_client(batch_size=50, flush_interval=0.2)
    for i in range(30):
        c.capture_message(f"m{i}")
    assert c.flush(3)
    assert len(server.events) == 30
    assert len(server.requests) < 30  # batched, not one request per event


def test_retries_on_503_then_succeeds(server, make_client):
    server.script = [(503, {}, b"{}"), (503, {}, b"{}")]
    c = make_client()
    c.capture_message("eventually")
    assert c.flush(5)
    assert [e["message"] for e in server.events][-1] == "eventually"
    assert c.transport.stats["retries"] == 2 and c.transport.stats["sent"] == 1


def test_honours_retry_after_header_on_429(server, make_client):
    server.script = [(429, {"Retry-After": "0.4"}, b"{}")]
    c = make_client()
    t0 = time.monotonic()
    c.capture_message("limited")
    assert c.flush(5)
    assert time.monotonic() - t0 >= 0.35  # waited for the server-provided delay
    assert len(server.requests) == 2


def test_reads_retry_after_from_nirikshan_error_body():
    body = json.dumps({"code": "rate_limited", "details": {"retry_after_seconds": 7}}).encode()
    assert parse_retry_after({}, body) == 7.0
    assert parse_retry_after({"Retry-After": "2"}, body) == 2.0
    assert parse_retry_after({}, b"not json") is None


def test_does_not_retry_on_400_or_401(server, make_client):
    server.script = [(401, {}, b'{"code": "unauthorized"}')]
    c = make_client()
    c.capture_message("bad token")
    assert c.flush(3)
    assert len(server.requests) == 1
    assert c.transport.stats["dropped_rejected"] == 1


def test_gives_up_after_max_retries_without_raising(server, make_client):
    server.script = [(500, {}, b"{}")] * 10
    c = make_client(max_retries=2)
    c.capture_message("doomed")
    assert c.flush(5)
    assert len(server.requests) == 3  # 1 try + 2 retries
    assert c.transport.stats["dropped_failed"] == 1


def test_server_down_never_raises_or_hangs_the_app(make_client):
    c = make_client(url="http://127.0.0.1:9/api/telemetry/logs", max_retries=1, timeout=0.3)
    t0 = time.monotonic()
    assert c.capture_message("nobody home") is True  # enqueue returns immediately
    assert time.monotonic() - t0 < 0.2
    assert c.flush(5)
    assert c.transport.stats["dropped_failed"] == 1


def test_full_queue_drops_and_counts_instead_of_blocking(server):
    server.delay = 0.3
    t = Transport(server.url, max_queue=2, batch_size=1, flush_interval=0.05, backoff_base=0.01)
    results = [t.submit({"service": "s", "message": f"m{i}", "level": "INFO"}) for i in range(10)]
    assert not all(results)
    assert t.stats["dropped_full"] >= 1
    t.close(timeout=3)


def test_flush_timeout_returns_false_when_server_is_slow(server, make_client):
    server.delay = 1.0
    c = make_client()
    c.capture_message("slow")
    assert c.flush(0.1) is False
    assert c.flush(5) is True
