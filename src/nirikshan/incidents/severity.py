"""Configurable incident-severity scoring.

Severity is derived from a weighted set of signals rather than hard-coded per
alert, so it can be reasoned about and tuned:

* service tier (user-facing critical services escalate)
* alert severity + how many correlated alerts
* measured error rate / latency multiple over SLO
* blast radius (number of impacted user-facing services)
"""

from __future__ import annotations

from dataclasses import dataclass

from nirikshan.domain.enums import AlertSeverity, Severity


@dataclass
class SeveritySignals:
    service_tier: int = 2
    alert_severity: AlertSeverity = AlertSeverity.HIGH
    correlated_alerts: int = 1
    error_rate: float | None = None
    slo_error_rate: float = 0.02
    latency_multiple_of_slo: float | None = None
    impacted_user_facing: int = 0
    dependency_outage: bool = False


def score(sig: SeveritySignals) -> tuple[Severity, float, list[str]]:
    points = 0.0
    reasons: list[str] = []

    tier_pts = {1: 4.0, 2: 2.0, 3: 0.5, 4: 0.0}.get(sig.service_tier, 1.0)
    points += tier_pts
    if sig.service_tier == 1:
        reasons.append("user-facing critical service (tier 1)")

    sev_pts = {
        AlertSeverity.CRITICAL: 4.0,
        AlertSeverity.HIGH: 2.5,
        AlertSeverity.MEDIUM: 1.0,
        AlertSeverity.LOW: 0.3,
    }[sig.alert_severity]
    points += sev_pts

    if sig.correlated_alerts >= 4:
        points += 2.0
        reasons.append(f"{sig.correlated_alerts} correlated alerts")
    elif sig.correlated_alerts >= 2:
        points += 1.0
        reasons.append(f"{sig.correlated_alerts} correlated alerts")

    if sig.error_rate is not None and sig.slo_error_rate > 0:
        mult = sig.error_rate / sig.slo_error_rate
        if mult >= 10:
            points += 3.0
            reasons.append(f"error rate {mult:.0f}x SLO")
        elif mult >= 3:
            points += 1.5
            reasons.append(f"error rate {mult:.1f}x SLO")

    if sig.latency_multiple_of_slo is not None:
        if sig.latency_multiple_of_slo >= 5:
            points += 2.5
            reasons.append(f"latency {sig.latency_multiple_of_slo:.1f}x SLO")
        elif sig.latency_multiple_of_slo >= 2:
            points += 1.0

    if sig.impacted_user_facing >= 2:
        points += 2.0
        reasons.append(f"{sig.impacted_user_facing} user-facing services in blast radius")
    elif sig.impacted_user_facing == 1:
        points += 1.0

    if sig.dependency_outage:
        points += 2.0
        reasons.append("hard dependency outage")

    if points >= 10:
        sev = Severity.SEV1
    elif points >= 6.5:
        sev = Severity.SEV2
    elif points >= 3.5:
        sev = Severity.SEV3
    else:
        sev = Severity.SEV4
    return sev, round(points, 2), reasons
