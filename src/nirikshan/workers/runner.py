"""Worker main loop: consume the Redis event stream + run periodic maintenance.

Two entry points:
* :func:`run` - standalone process (the ``worker`` container). Installs signal
  handlers and owns engine/logging setup.
* :func:`serve` - reusable loop driven by a ``stop_check`` callable, used both by
  :func:`run` and by the in-process worker thread started from the API lifespan
  (:func:`start_in_process`). It assumes engine/logging are already configured.
"""

from __future__ import annotations

import signal
import socket
import threading
import time
from collections.abc import Callable

from nirikshan.core.config import get_settings
from nirikshan.core.db import init_engine, session_scope
from nirikshan.core.logging import configure_logging, get_logger
from nirikshan.core.redis_bus import ack_event, ensure_group, is_healthy, read_events
from nirikshan.workers.handlers import HANDLERS

log = get_logger("workers.runner")

_MAINTENANCE_EVERY = 120  # seconds


def _dispatch(event_type: str, payload: dict) -> None:
    handler = HANDLERS.get(event_type)
    if handler is None:
        return
    try:
        with session_scope() as db:
            handler(db, payload)
    except Exception as exc:
        log.error("worker.handler_failed", event_type=event_type, error=str(exc))


def _maintenance() -> None:
    try:
        with session_scope() as db:
            from nirikshan.telemetry.aggregate import refresh_all_health
            from nirikshan.telemetry.retention import enforce_retention

            refresh_all_health(db)
            enforce_retention(db)
    except Exception as exc:
        log.warning("worker.maintenance_failed", error=str(exc))


def serve(
    stop_check: Callable[[], bool],
    *,
    consumer: str | None = None,
    block_ms: int = 2000,
    label: str = "worker",
    max_iterations: int | None = None,
) -> None:
    """Run the consume + maintenance loop until ``stop_check()`` returns True
    (or ``max_iterations`` loop passes have completed, when set)."""
    consumer = consumer or f"{label}-{socket.gethostname()}-{int(time.time())}"
    if is_healthy():
        ensure_group()
        log.info("worker.started", consumer=consumer, mode=label)
    else:
        log.warning("worker.no_redis", detail="event consumption disabled; maintenance only")

    last_maint = 0.0
    iterations = 0
    while not stop_check():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        now = time.time()
        if now - last_maint > _MAINTENANCE_EVERY:
            _maintenance()
            last_maint = now

        if not is_healthy():
            time.sleep(2)
            continue

        try:
            batch = read_events(consumer, count=32, block_ms=block_ms)
        except Exception as exc:
            log.warning("worker.read_failed", error=str(exc))
            time.sleep(1)
            continue

        for stream_id, event in batch:
            _dispatch(event.get("type"), event.get("payload", {}))
            try:
                ack_event(stream_id)
            except Exception as exc:
                log.warning("worker.ack_failed", stream_id=stream_id, error=str(exc))

    log.info("worker.exited", mode=label)


def run(once: bool = False) -> None:
    """Standalone worker process entry point."""
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    serve(stop.is_set, max_iterations=1 if once else None, block_ms=200 if once else 2000)


# --------------------------------------------------------------------------- #
# In-process worker (single-service deployments)
# --------------------------------------------------------------------------- #
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def start_in_process() -> bool:
    """Start the worker loop on a daemon thread. Idempotent. Returns True if started."""
    global _thread, _stop_event
    if _thread and _thread.is_alive():
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=serve,
        args=(_stop_event.is_set,),
        kwargs={"label": "in-process", "block_ms": 1000},
        name="nirikshan-worker",
        daemon=True,
    )
    _thread.start()
    return True


def stop_in_process(timeout: float = 5.0) -> None:
    global _thread, _stop_event
    if _stop_event:
        _stop_event.set()
    if _thread:
        _thread.join(timeout=timeout)
    _thread = None
    _stop_event = None


def drain(max_batches: int = 50) -> int:
    """Process all currently pending events once (used by tests/E2E)."""
    settings = get_settings()
    init_engine(settings)
    if not is_healthy():
        return 0
    ensure_group()
    consumer = f"drain-{int(time.time() * 1000)}"
    processed = 0
    for _ in range(max_batches):
        batch = read_events(consumer, count=64, block_ms=200)
        if not batch:
            break
        for stream_id, event in batch:
            _dispatch(event.get("type"), event.get("payload", {}))
            ack_event(stream_id)
            processed += 1
    return processed
