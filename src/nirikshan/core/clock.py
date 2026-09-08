"""Single source of truth for "now".

Centralising time makes deterministic tests and the demo scenario generator
possible: tests can freeze the clock instead of sprinkling ``monkeypatch`` calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

_frozen: datetime | None = None


def utcnow() -> datetime:
    """Timezone-aware current UTC time, or the frozen value when set."""
    return _frozen or datetime.now(UTC)


def freeze(value: datetime) -> None:
    global _frozen
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    _frozen = value


def unfreeze() -> None:
    global _frozen
    _frozen = None
