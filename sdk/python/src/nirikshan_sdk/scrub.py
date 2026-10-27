"""Remove obvious secrets before anything leaves the process."""

from __future__ import annotations

import re
from typing import Any

FILTERED = "[Filtered]"
_SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|secret|token|authorization|api[_-]?key|cookie|session|credential|private[_-]?key",
    re.IGNORECASE,
)
_SENSITIVE_QS = re.compile(
    r"([?&](?:[^=&#]*(?:pass|secret|token|key|auth|session)[^=&#]*)=)[^&#]*", re.IGNORECASE
)
_MAX_DEPTH = 8


def scrub_url(url: str) -> str:
    """Filter sensitive query-string values in a URL."""
    return _SENSITIVE_QS.sub(lambda m: m.group(1) + FILTERED, url)


def scrub(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with values under sensitive-looking keys replaced."""
    if _depth > _MAX_DEPTH:
        return FILTERED
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _SENSITIVE_KEY.search(k):
                out[k] = FILTERED
            else:
                out[k] = scrub(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return scrub_url(value) if "?" in value else value
    return value
