"""Redis-backed fixed-window rate limiting.

Protects telemetry ingestion, AI investigation and remediation endpoints
(spec 47). Fails open if Redis is unavailable - availability of the core
platform beats strict limiting.
"""

from __future__ import annotations

import time

import redis

from nirikshan.core.config import get_settings
from nirikshan.core.logging import get_logger
from nirikshan.core.redis_bus import get_client

log = get_logger("security.ratelimit")


class RateLimit:
    def __init__(self, name: str):
        self.name = name
        self.count, self.window = get_settings().rate(name)

    def check(self, identity: str) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, retry_after_seconds)."""
        now = int(time.time())
        bucket = now // self.window
        key = f"nirikshan:rl:{self.name}:{identity}:{bucket}"
        try:
            client = get_client()
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window + 1)
            current, _ = pipe.execute()
        except redis.RedisError as exc:  # fail open
            log.warning("ratelimit.unavailable", error=str(exc))
            return True, self.count, 0
        current = int(current)
        if current > self.count:
            retry = self.window - (now % self.window)
            return False, 0, retry
        return True, max(self.count - current, 0), 0
