"""A real local HTTP server the SDK talks to, scriptable per test (no mocking of the transport)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.script: list[tuple[int, dict, bytes]] = []  # responses consumed in order; default 200
        self.delay = 0.0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n)
                outer.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": json.loads(raw or b"{}")}
                )
                if outer.delay:
                    import time

                    time.sleep(outer.delay)
                status, headers, body = outer.script.pop(0) if outer.script else (200, {}, b'{"accepted": 1}')
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # silence
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/telemetry/logs"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def events(self) -> list[dict]:
        return [e for r in self.requests for e in r["body"].get("logs", [])]

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.stop()


@pytest.fixture
def make_client(server):
    from nirikshan_sdk import Client

    made = []

    def _make(**kw):
        kw.setdefault("install_hooks", False)
        kw.setdefault("flush_interval", 0.05)
        kw.setdefault("backoff_base", 0.01)
        c = Client(kw.pop("url", server.url), kw.pop("service", "checkout"), **kw)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close(timeout=1.0)
