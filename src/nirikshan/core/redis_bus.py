"""Redis connectivity: cache, event streams, pub/sub, rate-limit primitives.

Design choices
--------------
* PostgreSQL remains authoritative for durable state. Redis Streams carry the
  event fan-out between the API and the background workers.
* If Redis is unreachable the API keeps serving: ``publish_event`` logs and
  drops the event rather than raising. Workers simply have nothing to consume.
* Unit tests inject ``fakeredis``; integration tests use a real Redis container.
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis

from nirikshan.core.config import get_settings
from nirikshan.core.logging import get_logger

log = get_logger("redis")

_client: redis.Redis | None = None
# Circuit breaker: once Redis fails we stop hammering it (each failed call would
# otherwise pay the full socket timeout) until this monotonic time passes.
_open_until: float = 0.0
_BREAKER_SECONDS = 15.0
_injected = False  # a test/fake client is in use -> never breaker-trip

EVENT_STREAM = "nirikshan:events"
CONSUMER_GROUP = "nirikshan-workers"


def set_client(client: redis.Redis | None) -> None:
    """Test hook: inject a fakeredis client (or ``None`` to reset)."""
    global _client, _open_until, _injected
    _client = client
    _open_until = 0.0
    _injected = client is not None


def _breaker_open() -> bool:
    return not _injected and time.monotonic() < _open_until


def _trip_breaker(exc: Exception) -> None:
    global _open_until
    if not _injected:
        _open_until = time.monotonic() + _BREAKER_SECONDS
        log.warning("redis.circuit_open", seconds=_BREAKER_SECONDS, error=str(exc))


def _reset_breaker() -> None:
    global _open_until
    _open_until = 0.0


class _BreakerOpen(redis.RedisError):
    """Raised instead of attempting a call while the breaker is open."""


def get_client() -> redis.Redis:
    """Return the client. Raises ``redis.RedisError`` fast if the breaker is open."""
    global _client
    if _breaker_open():
        raise _BreakerOpen("redis circuit breaker open")
    if _client is None:
        settings = get_settings()
        _client = redis.Redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
        )
    return _client


def is_healthy() -> bool:
    if _breaker_open():
        return False
    try:
        get_client().ping()
        _reset_breaker()
        return True
    except redis.RedisError as exc:
        _trip_breaker(exc)
        return False


# --------------------------------------------------------------------------- #
# Events (Redis Streams)
# --------------------------------------------------------------------------- #
def publish_event(event_type: str, payload: dict[str, Any]) -> str | None:
    """Append an event to the shared stream. Returns the stream id or ``None``."""
    settings = get_settings()
    body = {"type": event_type, "payload": json.dumps(payload, default=str)}
    try:
        client = get_client()
        sid = client.xadd(EVENT_STREAM, body, maxlen=settings.redis_stream_maxlen, approximate=True)
        _reset_breaker()
        return sid
    except _BreakerOpen:
        return None
    except redis.RedisError as exc:
        _trip_breaker(exc)
        log.warning("event.publish_failed", event_type=event_type, error=str(exc))
        return None


def ensure_group(stream: str = EVENT_STREAM, group: str = CONSUMER_GROUP) -> None:
    try:
        get_client().xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def read_events(
    consumer: str,
    *,
    group: str = CONSUMER_GROUP,
    stream: str = EVENT_STREAM,
    count: int = 32,
    block_ms: int = 2000,
) -> list[tuple[str, dict[str, Any]]]:
    """Read a batch for a consumer group. Returns ``[(stream_id, event_dict), ...]``."""
    client = get_client()
    resp = client.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
    out: list[tuple[str, dict[str, Any]]] = []
    for _stream, entries in resp or []:
        for stream_id, fields in entries:
            payload = json.loads(fields.get("payload", "{}"))
            out.append((stream_id, {"type": fields.get("type"), "payload": payload}))
    return out


def ack_event(stream_id: str, *, group: str = CONSUMER_GROUP, stream: str = EVENT_STREAM) -> None:
    get_client().xack(stream, group, stream_id)


# --------------------------------------------------------------------------- #
# Pub/Sub (SSE fan-out to browsers)
# --------------------------------------------------------------------------- #
PUBSUB_CHANNEL = "nirikshan:live"


def broadcast(payload: dict[str, Any]) -> None:
    try:
        get_client().publish(PUBSUB_CHANNEL, json.dumps(payload, default=str))
        _reset_breaker()
    except _BreakerOpen:
        return
    except redis.RedisError as exc:  # pragma: no cover
        _trip_breaker(exc)
        log.warning("broadcast.failed", error=str(exc))


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #
def cache_get_json(key: str) -> Any | None:
    try:
        raw = get_client().get(key)
        return json.loads(raw) if raw else None
    except redis.RedisError:
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int = 30) -> None:
    try:
        get_client().set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except redis.RedisError:  # pragma: no cover
        pass


def cache_invalidate(*keys: str) -> None:
    try:
        if keys:
            get_client().delete(*keys)
    except redis.RedisError:  # pragma: no cover
        pass
