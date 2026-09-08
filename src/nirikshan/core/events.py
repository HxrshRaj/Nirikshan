"""Canonical event catalogue for the event-driven pipeline.

Events are published to a Redis Stream by the API / services and consumed by
the background workers (detection, incident, remediation). They are also
mirrored to a Redis pub/sub channel for browser SSE.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from nirikshan.core import redis_bus


class EventType(StrEnum):
    TELEMETRY_RECEIVED = "TELEMETRY_RECEIVED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    ALERT_CREATED = "ALERT_CREATED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_UPDATED = "INCIDENT_UPDATED"
    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    REMEDIATION_APPROVED = "REMEDIATION_APPROVED"
    REMEDIATION_REJECTED = "REMEDIATION_REJECTED"
    REMEDIATION_STARTED = "REMEDIATION_STARTED"
    REMEDIATION_COMPLETED = "REMEDIATION_COMPLETED"
    REMEDIATION_FAILED = "REMEDIATION_FAILED"
    REMEDIATION_ROLLED_BACK = "REMEDIATION_ROLLED_BACK"
    DEPLOYMENT_RECORDED = "DEPLOYMENT_RECORDED"


def emit(event_type: EventType | str, payload: dict[str, Any]) -> None:
    """Publish to the durable stream and mirror to the live pub/sub channel.

    Event delivery is best-effort: a broken event bus must never abort the
    business transaction that produced the event (spec 63, 82).
    """
    from nirikshan.core.logging import get_logger

    et = str(event_type)
    try:
        redis_bus.publish_event(et, payload)
    except Exception as exc:
        get_logger("events").warning("emit.stream_failed", event_type=et, error=str(exc))
    try:
        redis_bus.broadcast({"event": et, **payload})
    except Exception as exc:
        get_logger("events").warning("emit.broadcast_failed", event_type=et, error=str(exc))
