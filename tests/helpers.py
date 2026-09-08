"""Small builders shared across tests."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from nirikshan.catalog.service import get_or_create_service
from nirikshan.core.clock import utcnow
from nirikshan.models import Service, TelemetryLog, TelemetryMetric


def make_service(db: Session, name: str = "svc-a", **kw) -> Service:
    svc = get_or_create_service(db, name, environment="production", **kw)
    db.flush()
    return svc


def seed_metric_series(
    db: Session,
    svc: Service,
    metric: str,
    *,
    minutes: int = 60,
    baseline: float = 100.0,
    noise: float = 2.0,
    spike_last_minutes: int = 0,
    spike_multiplier: float = 1.0,
) -> None:
    now = utcnow()
    rows = []
    for i in range(minutes):
        ts = now - timedelta(minutes=minutes - i)
        val = baseline + ((i % 5) - 2) * (noise / 2)
        if spike_last_minutes and i >= minutes - spike_last_minutes:
            val = baseline * spike_multiplier
        rows.append(
            TelemetryMetric(
                ts=ts, ingested_at=now, environment_id=svc.environment_id, service_id=svc.id,
                service_name=svc.name, metric_name=metric, value=val, unit="count", labels={},
            )
        )
    db.add_all(rows)
    db.flush()


def seed_logs(db: Session, svc: Service, *, level: str = "ERROR", count: int = 10, message: str = "boom") -> None:
    now = utcnow()
    db.add_all(
        [
            TelemetryLog(
                ts=now - timedelta(seconds=i * 5), ingested_at=now, environment_id=svc.environment_id,
                service_id=svc.id, service_name=svc.name, level=level, message=message, attributes={},
            )
            for i in range(count)
        ]
    )
    db.flush()
