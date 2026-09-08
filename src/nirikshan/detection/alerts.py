"""Alert-rule evaluation.

Scope (spec 16): enough of a rule engine to demonstrate correct threshold +
"for duration" evaluation over metric / error-rate / latency / log / health
signals - not a Prometheus replacement.

A rule fires when its condition has held continuously for ``for_seconds``.
``breaching_since`` on the rule row tracks that dwell time across evaluations.
Firing creates (or refreshes) an :class:`Alert` with a stable ``fingerprint``
used later for deduplication and incident correlation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.events import EventType, emit
from nirikshan.core.ids import short_token
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import (
    AlertSignalKind,
    AlertState,
    ComparisonOp,
)
from nirikshan.models import Alert, AlertRule, Service, TelemetryLog, TelemetryMetric
from nirikshan.telemetry.aggregate import compute_service_health

log = get_logger("detection.alerts")

_CMP = {
    ComparisonOp.GT: lambda a, b: a > b,
    ComparisonOp.GTE: lambda a, b: a >= b,
    ComparisonOp.LT: lambda a, b: a < b,
    ComparisonOp.LTE: lambda a, b: a <= b,
    ComparisonOp.EQ: lambda a, b: abs(a - b) < 1e-9,
}


@dataclass
class Evaluation:
    breaching: bool
    observed: float | None
    detail: str


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(p.lower() for p in parts if p).encode()).hexdigest()[:32]


def _window_metric_value(
    db: Session, service_id: str, metric: str, window_seconds: int, agg: str = "avg"
) -> float | None:
    since = utcnow() - timedelta(seconds=window_seconds)
    col = TelemetryMetric.value
    fn = {"avg": func.avg, "max": func.max, "min": func.min, "sum": func.sum}.get(agg, func.avg)
    return db.scalar(
        select(fn(col)).where(
            TelemetryMetric.service_id == service_id,
            TelemetryMetric.metric_name == metric,
            TelemetryMetric.ts >= since,
        )
    )


def _evaluate(db: Session, rule: AlertRule, service: Service) -> Evaluation:
    kind = AlertSignalKind(rule.signal_kind)
    cmp = _CMP[ComparisonOp(rule.comparison)]
    w = rule.window_seconds

    if kind in (AlertSignalKind.METRIC, AlertSignalKind.RESOURCE, AlertSignalKind.LATENCY):
        metric = rule.subject or (
            "request_latency_ms" if kind == AlertSignalKind.LATENCY else ""
        )
        agg = "max" if kind == AlertSignalKind.LATENCY else "avg"
        val = _window_metric_value(db, service.id, metric, w, agg)
        if val is None:
            return Evaluation(False, None, f"no data for {metric}")
        return Evaluation(cmp(val, rule.threshold), float(val), f"{metric} {agg}={val:.3f}")

    if kind == AlertSignalKind.ERROR_RATE:
        health = compute_service_health(db, service, window_seconds=w)
        val = health.error_rate
        if val is None:
            return Evaluation(False, None, "no request/error data")
        return Evaluation(cmp(val, rule.threshold), float(val), f"error_rate={val:.4f}")

    if kind == AlertSignalKind.LOG_MATCH:
        since = utcnow() - timedelta(seconds=w)
        n = (
            db.scalar(
                select(func.count())
                .select_from(TelemetryLog)
                .where(
                    TelemetryLog.service_id == service.id,
                    TelemetryLog.ts >= since,
                    TelemetryLog.message.ilike(f"%{rule.subject}%"),
                )
            )
            or 0
        )
        return Evaluation(cmp(n, rule.threshold), float(n), f"{n} logs matching {rule.subject!r}")

    if kind == AlertSignalKind.SERVICE_HEALTH:
        health = compute_service_health(db, service, window_seconds=w)
        unhealthy = 1.0 if health.health.value in ("DEGRADED", "UNHEALTHY") else 0.0
        return Evaluation(unhealthy >= 1.0, unhealthy, f"health={health.health.value}")

    return Evaluation(False, None, "unsupported signal kind")


def _fire_or_refresh(db: Session, rule: AlertRule, service: Service, ev: Evaluation) -> Alert:
    fp = fingerprint(service.name, rule.signal_kind, rule.subject, rule.severity)
    existing = db.scalar(
        select(Alert).where(Alert.fingerprint == fp, Alert.state == AlertState.FIRING.value)
    )
    now = utcnow()
    if existing:
        existing.observed_value = ev.observed
        existing.context = {**(existing.context or {}), "last_detail": ev.detail, "refreshed_at": now.isoformat()}
        db.add(existing)
        return existing

    alert = Alert(
        ref="ALR-" + short_token(6),
        rule_id=rule.id,
        environment_id=rule.environment_id,
        service_id=service.id,
        service_name=service.name,
        title=f"{rule.name} on {service.name}",
        signal_kind=rule.signal_kind,
        subject=rule.subject,
        severity=rule.severity,
        state=AlertState.FIRING.value,
        observed_value=ev.observed,
        threshold=rule.threshold,
        fired_at=now,
        fingerprint=fp,
        context={"rule": rule.name, "detail": ev.detail, "comparison": rule.comparison},
    )
    db.add(alert)
    db.flush()
    rule.active_alert_id = alert.id
    emit(
        EventType.ALERT_CREATED,
        {
            "alert_ref": alert.ref,
            "alert_id": alert.id,
            "service": service.name,
            "environment_id": rule.environment_id,
            "severity": alert.severity,
            "signal_kind": alert.signal_kind,
            "fingerprint": fp,
            "title": alert.title,
        },
    )
    log.info("alert.fired", ref=alert.ref, service=service.name, rule=rule.name)
    return alert


def _resolve(db: Session, rule: AlertRule) -> None:
    if not rule.active_alert_id:
        return
    alert = db.get(Alert, rule.active_alert_id)
    if alert and alert.state == AlertState.FIRING.value:
        alert.state = AlertState.RESOLVED.value
        alert.resolved_at = utcnow()
        db.add(alert)
        emit(EventType.ALERT_RESOLVED, {"alert_ref": alert.ref, "service": alert.service_name})
        log.info("alert.resolved", ref=alert.ref)
    rule.active_alert_id = None


def _breach_since(db: Session, rule: AlertRule, service: Service, now) -> object:
    """Best-effort estimate of when ``rule`` began breaching for ``service``.

    For metric signals we walk the series backwards from now while the value
    stays on the breaching side of the threshold. For non-series signals we
    assume it has been breaching for one evaluation window.
    """
    kind = AlertSignalKind(rule.signal_kind)
    cmp = _CMP[ComparisonOp(rule.comparison)]
    if kind in (AlertSignalKind.METRIC, AlertSignalKind.RESOURCE, AlertSignalKind.LATENCY):
        metric = rule.subject or ("request_latency_ms" if kind == AlertSignalKind.LATENCY else "")
        since = now - timedelta(seconds=max(rule.window_seconds * 6, 1800))
        rows = db.execute(
            select(TelemetryMetric.ts, TelemetryMetric.value)
            .where(
                TelemetryMetric.service_id == service.id,
                TelemetryMetric.metric_name == metric,
                TelemetryMetric.ts >= since,
            )
            .order_by(TelemetryMetric.ts.desc())
        ).all()
        started = now
        for ts, value in rows:
            if cmp(float(value), rule.threshold):
                started = ts
            else:
                break
        return started
    return now - timedelta(seconds=rule.window_seconds)


def evaluate_rule(db: Session, rule: AlertRule) -> Alert | None:
    if not rule.enabled:
        return None
    now = utcnow()
    services: list[Service] = []
    if rule.service_id:
        svc = db.get(Service, rule.service_id)
        if svc:
            services = [svc]
    else:
        services = list(
            db.scalars(select(Service).where(Service.environment_id == rule.environment_id))
        )

    fired: Alert | None = None
    any_breach = False
    for svc in services:
        ev = _evaluate(db, rule, svc)
        if ev.breaching:
            any_breach = True
            # Anchor the dwell timer to when the signal actually started breaching
            # (inferred from series history), so a single evaluation pass still
            # respects `for_seconds` semantics instead of needing repeated ticks.
            started = _breach_since(db, rule, svc, now)
            if rule.breaching_since is None or started < rule.breaching_since:
                rule.breaching_since = started
            dwell = (now - rule.breaching_since).total_seconds()
            if dwell >= rule.for_seconds:
                fired = _fire_or_refresh(db, rule, svc, ev)
    if not any_breach:
        rule.breaching_since = None
        _resolve(db, rule)

    rule.last_evaluated_at = now
    db.add(rule)
    return fired


def evaluate_all_rules(db: Session, *, environment_id: str | None = None) -> list[Alert]:
    stmt = select(AlertRule).where(AlertRule.enabled.is_(True))
    if environment_id:
        stmt = stmt.where(AlertRule.environment_id == environment_id)
    out: list[Alert] = []
    for rule in db.scalars(stmt):
        try:
            a = evaluate_rule(db, rule)
            if a:
                out.append(a)
        except Exception as exc:
            log.warning("alert.eval_failed", rule=rule.name, error=str(exc))
    return out
