"""Typed contracts exchanged between the agents and the provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


@dataclass
class Hypothesis:
    title: str
    category: str
    rationale: str
    confidence: float
    supporting_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    root_cause: str
    confidence: float
    summary: str
    hypotheses: list[Hypothesis]
    contributing_factors: list[str]
    recommended_actions: list[str]
    usage: Usage
    is_mock: bool
    provider: str
    model: str
    # ids of evidence the model actually used (post-validation)
    grounded_evidence_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RemediationPlan:
    action_name: str
    parameters: dict
    rationale: str
    risk: str  # LOW|MEDIUM|HIGH
    expected_impact: str
    rollback_plan: str
    verification: dict
    confidence: float
    usage: Usage
    is_mock: bool
    provider: str
    model: str
    alternatives: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
