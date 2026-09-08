"""Worker main loop: consume the Redis event stream + run periodic maintenance."""

from __future__ import annotations

import signal
import socket
import time

from nirikshan.core.config import get_settings
from nirikshan.core.db import init_engine, session_scope
from nirikshan.core.logging import configure_logging, get_logger
from nirikshan.core.redis_bus import ack_event, ensure_group, is_healthy, read_events
from nirikshan.workers.handlers import HANDLERS

log = get_logger("workers.runner")

_running = True
_MAINTENANCE_EVERY = 120  # seconds


def _stop(*_a):
    global _running
    _running = False
    log.info("worker.stopping")


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


def run(once: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    consumer = f"worker-{socket.gethostname()}-{int(time.time())}"
    if is_healthy():
        ensure_group()
        log.info("worker.started", consumer=consumer)
    else:
        log.warning("worker.no_redis", detail="event consumption disabled; maintenance only")

    last_maint = 0.0
    while _running:
        now = time.time()
        if now - last_maint > _MAINTENANCE_EVERY:
            _maintenance()
            last_maint = now

        if not is_healthy():
            time.sleep(2)
            if once:
                break
            continue

        try:
            batch = read_events(consumer, count=32, block_ms=2000)
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

        if once:
            break

    log.info("worker.exited")


def drain(max_batches: int = 50) -> int:
    """Process all currently pending events once (used by tests/E2E)."""
    settings = get_settings()
    init_engine(settings)
    if not is_healthy():
        return 0
    ensure_group()
    consumer = f"drain-{int(time.time()*1000)}"
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
