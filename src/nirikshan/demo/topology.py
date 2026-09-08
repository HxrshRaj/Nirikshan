"""The standard Nirikshan demo topology + baseline alert rules.

    Frontend Web  ->  API Gateway  ->  Order Service ---> Payment Service --> PostgreSQL
                                          |          \--> Inventory Service -> PostgreSQL
                                          \--> Notification Service -> Redis
    (Payment, Order, Inventory also use Redis for caching.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from nirikshan.catalog.service import add_dependency, get_or_create_service
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import AlertSeverity, AlertSignalKind, ComparisonOp
from nirikshan.models import AlertRule, Service
from nirikshan.schemas.catalog import DependencyIn

log = get_logger("demo.topology")

ENVIRONMENT = "production"


@dataclass
class SvcDef:
    name: str
    display: str
    kind: str
    tier: int
    slo_latency_ms_p95: float = 300.0
    slo_error_rate: float = 0.02
    owner_team: str = "platform"
    baseline: dict = field(default_factory=dict)


SERVICES: list[SvcDef] = [
    SvcDef("web-frontend", "Web Frontend", "service", 1, 400, 0.02, "web",
           {"request_latency_ms": 180, "request_count": 900, "error_rate": 0.006,
            "cpu_usage": 0.35, "memory_usage": 0.5}),
    SvcDef("api-gateway", "API Gateway", "service", 1, 250, 0.01, "platform",
           {"request_latency_ms": 90, "request_count": 1400, "error_rate": 0.004,
            "cpu_usage": 0.4, "memory_usage": 0.55, "queue_depth": 4}),
    SvcDef("order-service", "Order Service", "service", 1, 300, 0.015, "orders",
           {"request_latency_ms": 120, "request_count": 850, "error_rate": 0.008,
            "cpu_usage": 0.45, "memory_usage": 0.6, "queue_depth": 6}),
    SvcDef("payment-service", "Payment Service", "service", 1, 280, 0.01, "payments",
           {"request_latency_ms": 140, "request_count": 620, "error_rate": 0.007,
            "cpu_usage": 0.5, "memory_usage": 0.62, "database_connections": 34, "queue_depth": 3}),
    SvcDef("inventory-service", "Inventory Service", "service", 2, 260, 0.02, "inventory",
           {"request_latency_ms": 110, "request_count": 700, "error_rate": 0.009,
            "cpu_usage": 0.4, "memory_usage": 0.55, "database_connections": 22}),
    SvcDef("notification-service", "Notification Service", "service", 3, 500, 0.03, "growth",
           {"request_latency_ms": 220, "request_count": 400, "error_rate": 0.012,
            "cpu_usage": 0.3, "memory_usage": 0.45, "queue_depth": 12}),
    SvcDef("postgresql", "PostgreSQL", "datastore", 1, 60, 0.005, "data",
           {"request_latency_ms": 12, "request_count": 3200, "error_rate": 0.001,
            "cpu_usage": 0.4, "memory_usage": 0.7, "database_connections": 120}),
    SvcDef("redis", "Redis", "cache", 2, 15, 0.002, "data",
           {"request_latency_ms": 3, "request_count": 5000, "error_rate": 0.0005,
            "cpu_usage": 0.2, "memory_usage": 0.35}),
]

DEPENDENCIES: list[tuple[str, str, str, bool]] = [
    ("web-frontend", "api-gateway", "sync", True),
    ("api-gateway", "order-service", "sync", True),
    ("order-service", "payment-service", "sync", True),
    ("order-service", "inventory-service", "sync", True),
    ("order-service", "notification-service", "async", False),
    ("payment-service", "postgresql", "datastore", True),
    ("inventory-service", "postgresql", "datastore", True),
    ("order-service", "postgresql", "datastore", True),
    ("payment-service", "redis", "sync", False),
    ("order-service", "redis", "sync", False),
    ("notification-service", "redis", "sync", True),
]

BASELINE: dict[str, dict[str, float]] = {s.name: s.baseline for s in SERVICES}


def ensure_topology(db: Session) -> list[Service]:
    created: list[Service] = []
    for s in SERVICES:
        svc = get_or_create_service(
            db, s.name, environment=ENVIRONMENT, kind=s.kind, tier=s.tier,
            display_name=s.display, owner_team=s.owner_team,
            slo_latency_ms_p95=s.slo_latency_ms_p95, slo_error_rate=s.slo_error_rate,
        )
        svc.display_name = s.display
        svc.tier = s.tier
        svc.kind = s.kind
        svc.slo_latency_ms_p95 = s.slo_latency_ms_p95
        svc.slo_error_rate = s.slo_error_rate
        db.add(svc)
        created.append(svc)
    db.flush()
    for up, down, kind, critical in DEPENDENCIES:
        add_dependency(db, DependencyIn(upstream=up, downstream=down, environment=ENVIRONMENT,
                                       kind=kind, critical=critical))
    _ensure_alert_rules(db, created)
    db.flush()
    log.info("demo.topology_ready", services=len(created))
    return created


def _ensure_alert_rules(db: Session, services: list[Service]) -> None:
    by_name = {s.name: s for s in services}
    env_id = services[0].environment_id
    from sqlalchemy import select

    def rule(name, svc, kind, subject, cmp, thr, for_s, sev, window=300):
        exists = db.scalar(select(AlertRule).where(AlertRule.name == name))
        if exists:
            return
        db.add(AlertRule(
            name=name, environment_id=env_id,
            service_id=by_name[svc].id if svc else None,
            signal_kind=kind.value, subject=subject, comparison=cmp.value,
            threshold=thr, for_seconds=for_s, window_seconds=window, severity=sev.value, enabled=True,
        ))

    for s in services:
        if s.kind in ("service",):
            rule(f"High error rate - {s.name}", s.name, AlertSignalKind.ERROR_RATE, "",
                 ComparisonOp.GT, max(s.slo_error_rate * 2.5, 0.03), 120, AlertSeverity.HIGH)
            rule(f"High latency p95 - {s.name}", s.name, AlertSignalKind.LATENCY, "request_latency_ms",
                 ComparisonOp.GT, s.slo_latency_ms_p95 * 2.0, 120, AlertSeverity.HIGH)
            rule(f"Error log surge - {s.name}", s.name, AlertSignalKind.LOG_MATCH, "error",
                 ComparisonOp.GT, 40, 120, AlertSeverity.MEDIUM)
    rule("DB connection saturation - payment-service", "payment-service", AlertSignalKind.RESOURCE,
         "database_connections", ComparisonOp.GT, 85, 120, AlertSeverity.CRITICAL)
    rule("Queue depth backlog - notification-service", "notification-service", AlertSignalKind.RESOURCE,
         "queue_depth", ComparisonOp.GT, 120, 120, AlertSeverity.MEDIUM)
    rule("Datastore unhealthy - postgresql", "postgresql", AlertSignalKind.SERVICE_HEALTH, "",
         ComparisonOp.GTE, 1, 120, AlertSeverity.CRITICAL)
