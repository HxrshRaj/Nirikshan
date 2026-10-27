"""Background transport: bounded queue, batching, retry with backoff, Retry-After, flush.

Design rules (they are what make an SDK safe to put inside someone else's app):
  * ``submit()`` never blocks and never raises. If the queue is full the event is dropped and counted.
  * Network I/O happens on one daemon thread, so an asyncio event loop is never blocked.
  * Retries use exponential backoff with jitter; a 429/503 ``Retry-After`` is honoured.
  * 4xx responses (other than 408/429) are not retried: the server said the payload is wrong.
"""

from __future__ import annotations

import json
import logging
import queue
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

log = logging.getLogger("nirikshan_sdk")

# (status, headers, body) or raises OSError-like for connection problems
SendFn = Callable[[bytes, dict], "tuple[int, dict, bytes]"]


def default_send(url: str, timeout: float) -> SendFn:
    def _send(body: bytes, headers: dict) -> "tuple[int, dict, bytes]":
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (url is configured by the app)
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() if e.fp else b""

    return _send


def parse_retry_after(headers: dict, body: bytes) -> Optional[float]:
    """Seconds to wait: the ``Retry-After`` header, else ``details.retry_after_seconds`` in the JSON body."""
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                return max(0.0, float(v))
            except ValueError:
                return None
    try:
        details = json.loads(body.decode("utf-8")).get("details") or {}
        val = details.get("retry_after_seconds")
        return max(0.0, float(val)) if val is not None else None
    except Exception:
        return None


class Transport:
    def __init__(
        self,
        url: str,
        *,
        ingest_token: Optional[str] = None,
        send: Optional[SendFn] = None,
        max_queue: int = 1000,
        batch_size: int = 50,
        flush_interval: float = 2.0,
        timeout: float = 5.0,
        max_retries: int = 4,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
    ) -> None:
        self._headers = {"Content-Type": "application/json", "User-Agent": "nirikshan-sdk-python"}
        if ingest_token:
            self._headers["X-Ingest-Token"] = ingest_token
        self._send = send or default_send(url, timeout)
        self._q: "queue.Queue[dict]" = queue.Queue(maxsize=max_queue)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._stop = threading.Event()
        self._cv = threading.Condition()
        self._pending = 0  # events accepted but not yet resolved (sent / dropped)
        self.stats = {"sent": 0, "dropped_full": 0, "dropped_rejected": 0, "dropped_failed": 0, "retries": 0}
        self._thread = threading.Thread(target=self._run, name="nirikshan-sdk-transport", daemon=True)
        self._thread.start()

    # --- public ---------------------------------------------------------------------------
    def submit(self, event: dict) -> bool:
        try:
            with self._cv:
                self._pending += 1
            self._q.put_nowait(event)
            return True
        except queue.Full:
            self._resolve(1)
            self.stats["dropped_full"] += 1
            return False

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until everything submitted so far is sent or dropped. True if fully drained."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._pending > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(left)
        return True

    def close(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        self._stop.set()
        self._thread.join(timeout=1.0)

    # --- internals ------------------------------------------------------------------------
    def _resolve(self, n: int) -> None:
        with self._cv:
            self._pending -= n
            self._cv.notify_all()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._q.get(timeout=self._flush_interval)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break
            try:
                self._deliver(batch)
            except Exception:  # the SDK must never die
                log.debug("nirikshan_sdk: unexpected transport error", exc_info=True)
                self.stats["dropped_failed"] += len(batch)
            finally:
                self._resolve(len(batch))

    def _deliver(self, batch: list[dict]) -> None:
        body = json.dumps({"logs": batch}, default=str).encode("utf-8")
        for attempt in range(self._max_retries + 1):
            wait: Optional[float] = None
            try:
                status, headers, resp = self._send(body, self._headers)
            except Exception as exc:  # connection refused, timeout, DNS ...
                log.debug("nirikshan_sdk: send failed: %s", exc)
                status, headers, resp = 0, {}, b""
            if 200 <= status < 300:
                self.stats["sent"] += len(batch)
                return
            if status in (408, 429, 500, 502, 503, 504) or status == 0:
                if attempt >= self._max_retries:
                    break
                wait = parse_retry_after(headers, resp) if status in (429, 503) else None
                if wait is None:
                    wait = min(self._backoff_cap, self._backoff_base * (2**attempt))
                    wait = random.uniform(wait / 2, wait)  # jitter
                wait = min(wait, self._backoff_cap)
                self.stats["retries"] += 1
                if self._stop.wait(wait):
                    break
                continue
            # other 4xx: the payload or credentials are wrong; retrying will not help
            log.debug("nirikshan_sdk: server rejected batch with %s", status)
            self.stats["dropped_rejected"] += len(batch)
            return
        self.stats["dropped_failed"] += len(batch)
