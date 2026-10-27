import logging

from nirikshan_sdk import scrub as scrub_mod
from nirikshan_sdk.client import new_scope
from nirikshan_sdk.events import fingerprint
from nirikshan_sdk.integrations.logging import NirikshanHandler


def _boom(x):
    return 1 / x


def _outer():
    return _boom(0)


def test_exception_event_has_frames_fingerprint_and_server_shape(server, make_client):
    c = make_client(release="1.4.2", environment="staging", ingest_token="tok")
    try:
        _outer()
    except ZeroDivisionError as e:
        assert c.capture_exception(e)
    assert c.flush(3)
    (ev,) = server.events
    assert ev["service"] == "checkout" and ev["environment"] == "staging"
    assert ev["level"] == "ERROR"
    assert ev["message"].startswith("ZeroDivisionError:")
    exc = ev["metadata"]["exception"]
    assert exc["type"] == "ZeroDivisionError"
    assert [f["function"] for f in exc["frames"]][-2:] == ["_outer", "_boom"]
    assert exc["frames"][-1]["context_line"] == "return 1 / x"
    assert ev["metadata"]["release"] == "1.4.2"
    assert len(ev["metadata"]["fingerprint"]) == 16
    assert server.requests[0]["headers"]["X-Ingest-Token"] == "tok"


def test_same_bug_groups_together_different_bug_does_not():
    def make(fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            from nirikshan_sdk.events import build_exception_event

            return build_exception_event(e, service="s", environment="e", release=None)

    a1 = make(_outer)
    a2 = make(_outer)  # same code path, same type -> same issue
    b = make(lambda: {}["missing"])
    assert a1["metadata"]["fingerprint"] == a2["metadata"]["fingerprint"]
    assert a1["metadata"]["fingerprint"] != b["metadata"]["fingerprint"]


def test_fingerprint_ignores_line_numbers_and_message():
    f1 = [{"filename": "/app/pay.py", "function": "charge", "lineno": 10, "in_app": True}]
    f2 = [{"filename": "/app/pay.py", "function": "charge", "lineno": 99, "in_app": True}]
    assert fingerprint("ValueError", f1) == fingerprint("ValueError", f2)
    assert fingerprint("ValueError", f1) != fingerprint("KeyError", f1)


def test_scope_tags_user_breadcrumbs_and_scrubbing(server, make_client):
    import nirikshan_sdk as sdk
    from nirikshan_sdk import client as client_mod

    c = make_client()
    client_mod._client = c  # use the module-level API against this client
    try:
        new_scope()
        sdk.set_tag("region", "ap-south-1")
        sdk.set_user({"id": "u1", "password": "hunter2"})
        sdk.add_breadcrumb("GET /cart?token=abc123&page=2", category="http", data={"api_key": "k"})
        sdk.capture_message("cart abandoned", level="warning")
        assert sdk.flush(3)
    finally:
        client_mod._client = None
    (ev,) = server.events
    assert ev["level"] == "WARN"
    md = ev["metadata"]
    assert md["tags"] == {"region": "ap-south-1"}
    assert md["user"]["password"] == "[Filtered]" and md["user"]["id"] == "u1"
    crumb = md["breadcrumbs"][0]
    assert "abc123" not in crumb["message"] and "page=2" in crumb["message"]
    assert crumb["data"]["api_key"] == "[Filtered]"


def test_scrub_nested_and_depth():
    out = scrub_mod.scrub({"a": {"Authorization": "Bearer x", "ok": [1, {"secret_key": "s"}]}})
    assert out["a"]["Authorization"] == "[Filtered]"
    assert out["a"]["ok"][1]["secret_key"] == "[Filtered]"


def test_before_send_can_modify_or_drop(server, make_client):
    c = make_client(before_send=lambda ev: None if "ignore" in ev["message"] else ev)
    assert not c.capture_message("please ignore me")
    assert c.capture_message("keep me")
    assert c.flush(3)
    assert [e["message"] for e in server.events] == ["keep me"]


def test_before_send_that_raises_drops_event_not_the_app(make_client):
    def bad(ev):
        raise RuntimeError("bug in user hook")

    c = make_client(before_send=bad)
    assert c.capture_message("x") is False  # no exception escapes


def test_sample_rate_zero_sends_nothing(server, make_client):
    c = make_client(sample_rate=0.0)
    assert not any(c.capture_message("m") for _ in range(20))
    assert c.flush(1)
    assert server.events == []


def test_logging_handler_reports_exceptions_and_messages(server, make_client):
    c = make_client()
    logger = logging.getLogger("tests.app")
    logger.propagate = False
    h = NirikshanHandler(c)
    logger.addHandler(h)
    try:
        try:
            raise KeyError("sku-9")
        except KeyError:
            logger.exception("lookup failed")
        logger.error("plain error")
        logger.warning("below threshold, ignored")
        assert c.flush(3)
    finally:
        logger.removeHandler(h)
    msgs = [e["message"] for e in server.events]
    assert any(m.startswith("KeyError") for m in msgs) and "plain error" in msgs
    assert len(msgs) == 2
