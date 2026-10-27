"""ASGI middleware (FastAPI, Starlette, Quart ...): per-request scope, breadcrumb, error capture.

    app.add_middleware(NirikshanASGIMiddleware)

The exception is captured and then re-raised, so your framework's own error handling is unchanged.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..client import Client, current_scope, get_client, new_scope
from ..scrub import scrub_url


class NirikshanASGIMiddleware:
    def __init__(self, app: Any, client: Optional[Client] = None) -> None:
        self.app = app
        self._client = client

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = self._client or get_client()
        sc = new_scope()  # contextvars: isolated per request task
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        sc.request_id = headers.get("x-request-id") or uuid.uuid4().hex
        method, path = scope.get("method", "GET"), scope.get("path", "")
        qs = scope.get("query_string", b"").decode("latin-1")
        if client:
            client.add_breadcrumb(
                f"{method} {scope_path(path, qs)}", category="http", data={"method": method}
            )
        status = {"code": None}

        async def _send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if client:
                current_scope().tags.setdefault("http.method", method)
                current_scope().tags.setdefault("http.path", path)
                client.capture_exception(exc)
            raise


def scope_path(path: str, query_string: str) -> str:
    return scrub_url(f"{path}?{query_string}") if query_string else path
