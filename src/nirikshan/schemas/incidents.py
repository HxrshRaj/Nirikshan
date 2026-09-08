from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from nirikshan.domain.enums import EvidenceKind, IncidentStatus, Severity


class IncidentEventOut(BaseModel):
    id: str
    at: datetime
    kind: str
    message: str
    actor: str
    source: str
    data: dict


class EvidenceOut(BaseModel):
    id: str
    kind: EvidenceKind
    ref_type: str
    ref_id: str
    summary: str
    observed_at: datetime | None
    weight: float
    collected_by: str
    data: dict


class HypothesisOut(BaseModel):
    id: str
    rank: int
    title: str
    category: str
    rationale: str
    confidence: float
    supporting_evidence_ids: list[str]
    is_selected: bool


class RCAOut(BaseModel):
    root_cause: str
    confidence: float | None
    summary: str
    contributing_factors: list[str]
    recommended_actions: list[str]
    affected_services: list[str]
    evidence: list[EvidenceOut]
    hypotheses: list[HypothesisOut]
    generated_by_run_id: str | None
    is_mock: bool = False


class IncidentSummary(BaseModel):
    id: str
    ref: str
    title: str
    severity: Severity
    status: IncidentStatus
    service: str
    environment_id: str
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    confidence: float | None
    alert_count: int
    affected_services: list[str]
    duration_seconds: float | None


class IncidentDetail(IncidentSummary):
    summary: str
    root_cause: str
    contributing_factors: list[str]
    recommended_actions: list[str]
    blast_radius: dict
    correlated_alert_refs: list[str]
    acknowledged_by: str | None
    resolved_by: str | None
    last_investigation_run_id: str | None
    events: list[IncidentEventOut]
    evidence: list[EvidenceOut]
    hypotheses: list[HypothesisOut]


class AcknowledgeIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class ResolveIn(BaseModel):
    resolution: str = Field(default="", max_length=2000)
    root_cause: str = Field(default="", max_length=2000)


class InvestigateIn(BaseModel):
    force: bool = False
    prompt_version: str | None = None
