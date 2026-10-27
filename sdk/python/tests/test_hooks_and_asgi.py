import asyncio
import sys
import threading

import pytest

from nirikshan_sdk import Client
from nirikshan_sdk.integrations.asgi import NirikshanASGIMiddleware


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_unhandled_thread_exception_is_captured(server):
    c = Client(server.url, "worker", flush_interval=0.05)
    try:
        t = threading.Thread(target=lambda: 1 / 0)
        t.start()
        t.join()
        assert c.flush(3)
    finally:
        c.close(1.0)
    assert any(e["metadata"]["exception"]["type"] == "ZeroDivisionError" for e in server.events)


def test_hooks_are_restored_on_close(server):
    before_ex, before_th = sys.excepthook, threading.excepthook
    c = Client(server.url, "x")
    assert sys.excepthook is not before_ex
    c.close(1.0)
    assert sys.excepthook is before_ex and threading.excepthook is before_th


def test_asyncio_unretrieved_task_exception_is_captured(server):
    c = Client(server.url, "async-svc", install_hooks=False, flush_interval=0.05)

    async def main():
        loop = asyncio.get_running_loop()
        c.install_asyncio_handler(loop)

        async def bad():
            raise ValueError("lost in a task")

        asyncio.ensure_future(bad())
        await asyncio.sleep(0.05)
        import gc

        gc.collect()  # "Task exception was never retrieved" fires on task finalisation
        await asyncio.sleep(0.05)

    try:
        asyncio.run(main())
        assert c.flush(3)
    finally:
        c.close(1.0)
    assert any("lost in a task" in e["message"] for e in server.events)


def _asgi_scope(path="/boom", qs=b"token=s3cret&x=1"):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": qs,
        "headers": [(b"x-request-id", b"req-7")],
    }


def test_asgi_middleware_captures_with_request_context_and_reraises(server):
    c = Client(server.url, "api", install_hooks=False, flush_interval=0.05)

    async def app(scope, receive, send):
        raise RuntimeError("handler exploded")

    async def run():
        mw = NirikshanASGIMiddleware(app, client=c)
        with pytest.raises(RuntimeError):
            await mw(_asgi_scope(), None, lambda m: None)

    try:
        asyncio.run(run())
        assert c.flush(3)
    finally:
        c.close(1.0)
    (ev,) = server.events
    assert ev["request_id"] == "req-7"
    assert ev["metadata"]["tags"]["http.path"] == "/boom"
    crumb = ev["metadata"]["breadcrumbs"][0]["message"]
    assert "s3cret" not in crumb and "x=1" in crumb


def test_asgi_concurrent_requests_do_not_leak_scope(server):
    c = Client(server.url, "api", install_hooks=False, flush_interval=0.05)

    async def app(scope, receive, send):
        await asyncio.sleep(0.01)
        raise RuntimeError(scope["path"])

    async def one(path):
        mw = NirikshanASGIMiddleware(app, client=c)
        with pytest.raises(RuntimeError):
            await mw(_asgi_scope(path, b""), None, lambda m: None)

    async def run():
        await asyncio.gather(*(one(f"/p{i}") for i in range(8)))

    try:
        asyncio.run(run())
        assert c.flush(3)
    finally:
        c.close(1.0)
    assert len(server.events) == 8
    for ev in server.events:  # each event carries only its own request's breadcrumb/tag
        assert len(ev["metadata"]["breadcrumbs"]) == 1
        assert ev["metadata"]["tags"]["http.path"] == ev["message"].split(": ")[1]
