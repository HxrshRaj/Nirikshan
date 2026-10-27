"""``logging`` integration: ERROR+ records become Nirikshan events (with the traceback when present)."""

from __future__ import annotations

import logging

from ..client import Client, get_client

_MAP = {logging.ERROR: "ERROR", logging.CRITICAL: "FATAL", logging.WARNING: "WARN"}


class NirikshanHandler(logging.Handler):
    def __init__(self, client: Client | None = None, level: int = logging.ERROR) -> None:
        super().__init__(level)
        self._client = client

    def emit(self, record: logging.LogRecord) -> None:
        # never report our own SDK's diagnostics (would loop when the server is down)
        if record.name.startswith("nirikshan_sdk"):
            return
        client = self._client or get_client()
        if client is None:
            return
        try:
            lvl = _MAP.get(record.levelno, "ERROR" if record.levelno > logging.ERROR else "INFO")
            if record.exc_info and record.exc_info[1] is not None:
                client.capture_exception(record.exc_info[1], level=lvl)
            else:
                client.capture_message(record.getMessage(), level=lvl)
        except Exception:
            self.handleError(record)
