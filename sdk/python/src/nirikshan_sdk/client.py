"""Client, per-task scope (contextvars, so it is correct under asyncio) and the module-level API."""

from __future__ import annotations

import contextvars
import logging
import random
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .events import build_exception_event, build_message_event
from .scrub import scrub
from .transport import SendFn, Transport

log = logging.getLogger("nirikshan_sdk")
_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR", "FATAL"}

BeforeSend = Callable[[dict], Optional[dict]]


class Scope:
    """Tags, user and breadcrumbs for the current thread / asyncio task."""

    __slots__ = ("tags", "user", "breadcrumbs", "request_id", "trace_id")

    def __init__(self) -> None:
        self.tags: dict[str, str] = {}
        self.user: dict[str, Any] = {}
        self.breadcrumbs: list[dict] = []
        self.request_id: Optional[str] = None
        self.trace_id: Optional[str] = None

    def copy(self) -> "Scope":
        s = Scope()
        s.tags, s.user = dict(self.tags), dict(self.user)
        s.breadcrumbs = list(self.breadcrumbs)
        s.request_id, s.trace_id = self.request_id, self.trace_id
        return s


_scope_var: contextvars.ContextVar[Optional[Scope]] = contextvars.ContextVar("nirikshan_scope", default=None)


def current_scope() -> Scope:
    s = _scope_var.get()
    if s is None:
        s = Scope()
        _scope_var.set(s)
    return s


def new_scope() -> Scope:
    """Start a fresh scope for the current context (the ASGI middleware does this per request)."""
    s = Scope()
    _scope_var.set(s)
    return s


class Client:
    def __init__(
        self,
        url: str,
        service: str,
        *,
        environment: str = "production",
        release: Optional[str] = None,
        ingest_token: Optional[str] = None,
        sample_rate: float = 1.0,
        before_send: Optional[BeforeSend] = None,
        max_breadcrumbs: int = 50,
        send: Optional[SendFn] = None,
        install_hooks: bool = True,
        **transport_opts: Any,
    ) -> None:
        if not service:
            raise ValueError("service is required")
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        self.service, self.environment, self.release = service, environment, release
        self.sample_rate, self.before_send, self.max_breadcrumbs = sample_rate, before_send, max_breadcrumbs
        self.transport = Transport(url, ingest_token=ingest_token, send=send, **transport_opts)
        self._orig_excepthook = None
        self._orig_thread_hook = None
        if install_hooks:
            self._install_hooks()

    # --- capture ------------------------------------------------------------------------
    def capture_exception(self, exc: Optional[BaseException] = None, *, level: str = "ERROR") -> bool:
        try:
            if exc is None:
                exc = sys.exc_info()[1]
            if exc is None:
                return False
            ev = build_exception_event(
                exc, service=self.service, environment=self.environment, release=self.release, level=level
            )
            return self._finish(ev)
        except Exception:
            log.debug("nirikshan_sdk: capture_exception failed", exc_info=True)
            return False

    def capture_message(self, message: str, *, level: str = "INFO") -> bool:
        try:
            level = level.upper()
            if level == "WARNING":
                level = "WARN"
            if level not in _LEVELS:
                level = "INFO"
            ev = build_message_event(
                message, service=self.service, environment=self.environment, release=self.release, level=level
            )
            return self._finish(ev)
        except Exception:
            log.debug("nirikshan_sdk: capture_message failed", exc_info=True)
            return False

    def add_breadcrumb(
        self, message: str, *, category: str = "default", level: str = "INFO", data: Optional[dict] = None
    ) -> None:
        crumbs = current_scope().breadcrumbs
        crumbs.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "category": category,
                "level": level,
                "message": str(message)[:500],
                "data": scrub(data or {}),
            }
        )
        del crumbs[: -self.max_breadcrumbs]

    def _finish(self, ev: dict) -> bool:
        if self.sample_rate < 1.0 and random.random() >= self.sample_rate:
            return False
        scope = current_scope()
        md = ev["metadata"]
        if scope.tags:
            md["tags"] = scope.tags.copy()
        if scope.user:
            md["user"] = scope.user.copy()
        if scope.breadcrumbs:
            md["breadcrumbs"] = list(scope.breadcrumbs)
        if scope.request_id:
            ev["request_id"] = scope.request_id[:64]
        if scope.trace_id:
            ev["trace_id"] = scope.trace_id[:64]
        ev["metadata"] = scrub(md)
        if self.before_send is not None:
            try:
                ev = self.before_send(ev)  # type: ignore[assignment]
            except Exception:
                log.debug("nirikshan_sdk: before_send raised; dropping event", exc_info=True)
                return False
            if ev is None:
                return False
        return self.transport.submit(ev)

    # --- lifecycle ----------------------------------------------------------------------
    def flush(self, timeout: float = 5.0) -> bool:
        return self.transport.flush(timeout)

    def close(self, timeout: float = 5.0) -> None:
        self._uninstall_hooks()
        self.transport.close(timeout)

    # --- hooks --------------------------------------------------------------------------
    def _install_hooks(self) -> None:
        self._orig_excepthook = sys.excepthook
        self._orig_thread_hook = threading.excepthook

        def _hook(exc_type, exc, tb):
            if exc is not None and not issubclass(exc_type, KeyboardInterrupt):
                self.capture_exception(exc, level="FATAL")
                self.flush(2.0)  # the interpreter is about to exit
            (self._orig_excepthook or sys.__excepthook__)(exc_type, exc, tb)

        def _thread_hook(args):
            if args.exc_value is not None and not issubclass(args.exc_type, SystemExit):
                self.capture_exception(args.exc_value, level="ERROR")
            if self._orig_thread_hook is not None:
                self._orig_thread_hook(args)

        sys.excepthook = _hook
        threading.excepthook = _thread_hook

    def _uninstall_hooks(self) -> None:
        if self._orig_excepthook is not None:
            sys.excepthook = self._orig_excepthook
            self._orig_excepthook = None
        if self._orig_thread_hook is not None:
            threading.excepthook = self._orig_thread_hook
            self._orig_thread_hook = None

    def install_asyncio_handler(self, loop) -> None:  # type: ignore[no-untyped-def]
        """Report exceptions from tasks nobody awaited ("Task exception was never retrieved")."""
        previous = loop.get_exception_handler()

        def _handler(lp, context):
            exc = context.get("exception")
            if exc is not None:
                self.capture_exception(exc)
            elif context.get("message"):
                self.capture_message(str(context["message"]), level="ERROR")
            if previous is not None:
                previous(lp, context)
            else:
                lp.default_exception_handler(context)

        loop.set_exception_handler(_handler)


# --- module-level API -------------------------------------------------------------------
_client: Optional[Client] = None


def init(url: str, service: str, **kwargs: Any) -> Client:
    global _client
    if _client is not None:
        _client.close(timeout=1.0)
    _client = Client(url, service, **kwargs)
    return _client


def get_client() -> Optional[Client]:
    return _client


def capture_exception(exc: Optional[BaseException] = None, **kw: Any) -> bool:
    return _client.capture_exception(exc, **kw) if _client else False


def capture_message(message: str, **kw: Any) -> bool:
    return _client.capture_message(message, **kw) if _client else False


def add_breadcrumb(message: str, **kw: Any) -> None:
    if _client:
        _client.add_breadcrumb(message, **kw)


def set_tag(key: str, value: Any) -> None:
    current_scope().tags[str(key)] = str(value)


def set_user(user: dict) -> None:
    current_scope().user = dict(user)


def flush(timeout: float = 5.0) -> bool:
    return _client.flush(timeout) if _client else True


def close(timeout: float = 5.0) -> None:
    global _client
    if _client:
        _client.close(timeout)
        _client = None
