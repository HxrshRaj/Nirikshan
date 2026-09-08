"""Named demo scenarios + an orchestrator that drives the full pipeline.

Each scenario seeds telemetry, then runs:

    detection (anomaly + baselines) -> alert evaluation -> incident correlation
    -> AI investigation -> (optionally) remediation proposal

so the whole platform can be exercised end-to-end from one call (spec 89-95).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.ai.investigator import investigate
from nirikshan.core.logging import get_logger
from nirikshan.demo.generator import FaultSpec, ScenarioSpec, generate
from nirikshan.detection.alerts import evaluate_all_rules
from nirikshan.detection.anomaly import scan_service
from nirikshan.incidents.engine import ingest_alert
from nirikshan.models import Alert, Incident, IncidentHypothesis, Service
from nirikshan.remediation.agent import propose_remediation
from nirikshan.telemetry.aggregate import refresh_all_health

log = get_logger("demo.scenarios")


SCENARIOS: dict[str, ScenarioSpec] = {
    "normal": ScenarioSpec(
        key="normal",
        title="Normal operation",
        description="Healthy traffic, latency and error rates across all services.",
        faults=[],
        expected_category="inconclusive",
    ),
    "db-exhaustion": ScenarioSpec(
        key="db-exhaustion",
        title="Payment database connection exhaustion",
        description="Payment Service saturates the PostgreSQL connection pool; latency and "
        "checkout errors climb.",
        expected_category="database_saturation",
        expected_service="payment-service",
        expected_evidence=["metric:database_connections", "metric:request_latency_ms", "logs:connection_errors"],
        faults=[
            FaultSpec(
                service="payment-service",
                category="database_saturation",
                metric_multipliers={
                    "database_connections": 3.1,
                    "request_latency_ms": 6.5,
                    "cpu_usage": 1.4,
                    "request_count": 0.85,
                },
                add_error_rate=0.13,
                error_log_message="could not acquire connection from pool: timeout acquiring connection (pool exhausted)",
                error_logs_per_min=6,
            ),
        ],
    ),
    "deploy-regression": ScenarioSpec(
        key="deploy-regression",
        title="Order Service deployment regression",
        description="Deployment v2.4.0 introduces a validation bug; error rate and latency rise "
        "minutes after rollout.",
        expected_category="deployment_regression",
        expected_service="order-service",
        expected_evidence=["metric:error_rate", "metric:request_latency_ms"],
        faults=[
            FaultSpec(
                service="order-service",
                category="deployment_regression",
                metric_multipliers={"request_latency_ms": 2.6, "cpu_usage": 1.25, "request_count": 0.95},
                add_error_rate=0.085,
                error_log_message="unhandled exception in OrderValidator.validate(): NullPointerException",
                error_logs_per_min=5,
                deployment={
                    "version": "v2.4.0",
                    "previous_version": "v2.3.7",
                    "minutes_before_fault": 6,
                    "change_summary": "Refactor order validation pipeline; add coupon engine",
                },
            ),
        ],
    ),
    "dependency-failure": ScenarioSpec(
        key="dependency-failure",
        title="PostgreSQL outage degrades Payment Service",
        description="PostgreSQL becomes unhealthy; Payment (and Inventory) that depend on it degrade.",
        expected_category="upstream_dependency_failure",
        expected_service="payment-service",
        expected_evidence=["dep:unhealthy:postgresql", "metric:request_latency_ms"],
        faults=[
            FaultSpec(
                service="postgresql",
                category="upstream_dependency_failure",
                metric_multipliers={"request_latency_ms": 14.0, "cpu_usage": 1.8, "error_rate": 1.0},
                add_error_rate=0.4,
                error_log_message="FATAL: connection to primary lost; failover in progress",
                error_logs_per_min=8,
                mark_datastore_unhealthy=True,
            ),
            FaultSpec(
                service="payment-service",
                category="upstream_dependency_failure",
                metric_multipliers={"request_latency_ms": 5.5, "database_connections": 1.9},
                add_error_rate=0.11,
                error_log_message="payment charge failed: database unavailable (deadline exceeded)",
                error_logs_per_min=5,
            ),
        ],
    ),
    "traffic-spike": ScenarioSpec(
        key="traffic-spike",
        title="Notification Service queue overload",
        description="A campaign drives a traffic spike; the notification queue backs up and latency rises.",
        expected_category="traffic_overload",
        expected_service="notification-service",
        expected_evidence=["metric:queue_depth", "metric:request_count"],
        faults=[
            FaultSpec(
                service="notification-service",
                category="traffic_overload",
                metric_multipliers={
                    "request_count": 5.5,
                    "queue_depth": 14.0,
                    "request_latency_ms": 3.2,
                    "cpu_usage": 1.9,
                },
                add_error_rate=0.05,
                error_log_message="notification dispatch timed out: worker pool saturated",
                error_logs_per_min=3,
            ),
        ],
    ),
}


@dataclass
class ScenarioRun:
    scenario: str
    seeded: dict
    anomalies: int
    alerts: list[str]
    incident_ref: str | None
    incident_id: str | None
    investigation_run_id: str | None
    root_cause: str | None
    confidence: float | None
    top_hypothesis_category: str | None
    remediation_ref: str | None
    expected_category: str
    category_match: bool | None


def run_scenario(
    db: Session,
    key: str,
    *,
    investigate_incident: bool = True,
    propose_fix: bool = False,
    minutes_history: int = 180,
) -> ScenarioRun:
    spec = SCENARIOS.get(key)
    if spec is None:
        raise KeyError(f"unknown scenario {key!r}; choose from {sorted(SCENARIOS)}")

    seeded = generate(db, scenario=spec, minutes_history=minutes_history)

    # mark datastore health explicitly for dependency-failure realism
    for f in spec.faults:
        if f.mark_datastore_unhealthy:
            svc = db.scalar(select(Service).where(Service.name == f.service))
            if svc:
                from nirikshan.domain.enums import ServiceHealth

                svc.health = ServiceHealth.UNHEALTHY.value
                db.add(svc)
    db.flush()

    refresh_all_health(db)

    anomalies = 0
    for svc in db.scalars(select(Service)):
        anomalies += len(scan_service(db, svc))
    db.flush()

    fired = evaluate_all_rules(db)
    db.flush()

    incident: Incident | None = None
    for alert in db.scalars(
        select(Alert).where(Alert.state == "FIRING", Alert.incident_id.is_(None)).order_by(Alert.fired_at)
    ):
        inc, _created = ingest_alert(db, alert)
        incident = incident or inc
    # prefer the incident on the expected service if several opened
    if spec.expected_service:
        want = db.scalar(
            select(Incident)
            .where(Incident.service_name == spec.expected_service)
            .order_by(Incident.detected_at.desc())
            .limit(1)
        )
        incident = want or incident
    db.flush()

    run_id = None
    top_cat = None
    if incident and investigate_incident:
        run = investigate(db, incident)
        run_id = run.run_id
        db.flush()
        db.refresh(incident)
        top = db.scalar(
            select(IncidentHypothesis)
            .where(IncidentHypothesis.incident_id == incident.id)
            .order_by(IncidentHypothesis.rank)
            .limit(1)
        )
        top_cat = top.category if top else None

    remediation_ref = None
    if incident and propose_fix:
        try:
            action = propose_remediation(db, incident)
            remediation_ref = action.ref if action else None
        except Exception as exc:
            log.warning("scenario.remediation_failed", error=str(exc))

    match = None
    if spec.expected_category != "inconclusive" and top_cat is not None:
        match = top_cat == spec.expected_category

    return ScenarioRun(
        scenario=key,
        seeded=seeded,
        anomalies=anomalies,
        alerts=[a.ref for a in fired],
        incident_ref=incident.ref if incident else None,
        incident_id=incident.id if incident else None,
        investigation_run_id=run_id,
        root_cause=incident.root_cause if incident else None,
        confidence=incident.confidence if incident else None,
        top_hypothesis_category=top_cat,
        remediation_ref=remediation_ref,
        expected_category=spec.expected_category,
        category_match=match,
    )
