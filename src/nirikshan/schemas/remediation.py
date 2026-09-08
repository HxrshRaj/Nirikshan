from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from nirikshan.domain.enums import RemediationStatus, RiskLevel


class RemediationProposeIn(BaseModel):
    force: bool = False


class ApprovalIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ExecutionOut(BaseModel):
    id: str
    attempt: int
    kind: str
    actor: str
    started_at: datetime
    finished_at: datetime | None
    ok: bool
    result: str
    before_state: dict
    after_state: dict
    verification: dict
    log: str


class ApprovalOut(BaseModel):
    id: str
    decision: str
    actor: str
    actor_role: str
    reason: str
    at: datetime


class RemediationOut(BaseModel):
    id: str
    ref: str
    incident_id: str
    proposed_by_run_id: str | None
    action_name: str
    parameters: dict
    rationale: str
    risk: RiskLevel
    expected_impact: str
    rollback_plan: str
    verification_plan: dict
    status: RemediationStatus
    mode: str
    policy_findings: list
    is_reversible: bool
    created_at: datetime
    approvals: list[ApprovalOut]
    executions: list[ExecutionOut]


class ActionSpecOut(BaseModel):
    name: str
    description: str
    parameters_schema: dict
    default_risk: RiskLevel
    reversible: bool
    requires_role: str
