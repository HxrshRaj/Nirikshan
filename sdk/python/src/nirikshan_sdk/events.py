"""Turn an exception into a Nirikshan log event (the server's existing ``/api/telemetry/logs`` shape)."""

from __future__ import annotations

import hashlib
import linecache
import os
import socket
import sys
import traceback
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Optional

from . import __version__

_STDLIB_PREFIXES = tuple(p for p in {os.path.dirname(os.__file__), sys.prefix, sys.base_prefix} if p)
_MAX_FRAMES = 50
_MAX_MESSAGE = 7900  # server limit is 8000


def _in_app(filename: str) -> bool:
    if "site-packages" in filename or "dist-packages" in filename:
        return False
    if filename.startswith("<"):
        return False
    return not filename.startswith(_STDLIB_PREFIXES)


def extract_frames(tb: Optional[TracebackType]) -> list[dict[str, Any]]:
    frames = []
    for fs in traceback.extract_tb(tb):
        frames.append(
            {
                "filename": fs.filename,
                "function": fs.name,
                "lineno": fs.lineno,
                "context_line": (linecache.getline(fs.filename, fs.lineno).strip() if fs.lineno else ""),
                "in_app": _in_app(fs.filename),
            }
        )
    return frames[-_MAX_FRAMES:]  # innermost frames matter most


def fingerprint(exc_type: str, frames: list[dict[str, Any]]) -> str:
    """Group the same bug together across deploys and messages.

    Uses the exception type plus the *function names and file basenames* of in-app frames.
    Line numbers and the message are left out on purpose: they change with every edit or input.
    """
    parts = [exc_type]
    app_frames = [f for f in frames if f.get("in_app")] or frames
    for f in app_frames:
        parts.append(f"{os.path.basename(f['filename'])}:{f['function']}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _base(service: str, environment: str, release: Optional[str], level: str, message: str) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "environment": environment,
        "level": level,
        "message": message[:_MAX_MESSAGE] or "(empty message)",
        "host": socket.gethostname()[:200],
        "metadata": {"sdk": {"name": "nirikshan-sdk-python", "version": __version__}, "release": release},
    }


def build_exception_event(
    exc: BaseException, *, service: str, environment: str, release: Optional[str], level: str = "ERROR"
) -> dict[str, Any]:
    exc_type = type(exc).__name__
    frames = extract_frames(exc.__traceback__)
    ev = _base(service, environment, release, level, f"{exc_type}: {exc}")
    ev["metadata"]["exception"] = {
        "type": exc_type,
        "module": type(exc).__module__,
        "value": str(exc)[:2000],
        "frames": frames,
    }
    ev["metadata"]["fingerprint"] = fingerprint(exc_type, frames)
    cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    if cause is not None:
        ev["metadata"]["exception"]["caused_by"] = f"{type(cause).__name__}: {cause}"[:500]
    return ev


def build_message_event(
    message: str, *, service: str, environment: str, release: Optional[str], level: str = "INFO"
) -> dict[str, Any]:
    ev = _base(service, environment, release, level, message)
    ev["metadata"]["fingerprint"] = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    return ev
