from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from nirikshan.domain.enums import (
    AlertSeverity,
    AlertSignalKind,
    AlertState,
    AnomalyMethod,
    ComparisonOp,
)


class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    environment: str = "production"
    service: str | None = None
    signal_kind: AlertSignalKind
    subject: str = Field(default="", max_length=120)
    comparison: ComparisonOp = ComparisonOp.GT
    threshold: float = 0.0
    for_seconds: int = Field(default=300, ge=0, le=3600)
    window_seconds: int = Field(default=300, ge=30, le=3600)
    severity: AlertSeverity = AlertSeverity.HIGH
    enabled: bool = True
    labels: dict = Field(default_factory=dict)


class AlertRuleOut(AlertRuleIn):
    id: str
    breaching_since: datetime | None = None
    last_evaluated_at: datetime | None = None


class AlertOut(BaseModel):
    id: str
    ref: str
    rule_id: str | None
    service: str
    environment_id: str
    title: str
    signal_kind: str
    subject: str
    severity: AlertSeverity
    state: AlertState
    observed_value: float | None
    threshold: float | None
    fired_at: datetime
    resolved_at: datetime | None
    fingerprint: str
    incident_id: str | None
    context: dict


class AnomalyOut(BaseModel):
    id: str
    detected_at: datetime
    service: str
    metric_name: str
    method: AnomalyMethod
    observed_value: float
    expected_low: float
    expected_high: float
    score: float
    confidence: float
    direction: str
    context: dict
