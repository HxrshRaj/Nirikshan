from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from nirikshan.domain.enums import DeploymentStatus, ServiceHealth


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="production", max_length=80)
    display_name: str = ""
    kind: str = Field(default="service", max_length=40)
    tier: int = Field(default=2, ge=1, le=4)
    owner_team: str = ""
    runbook_url: str = ""
    slo_latency_ms_p95: float = 300.0
    slo_error_rate: float = 0.02
    attributes: dict = Field(default_factory=dict)


class ServiceOut(BaseModel):
    id: str
    name: str
    display_name: str
    environment: str
    kind: str
    tier: int
    owner_team: str
    runbook_url: str
    health: ServiceHealth
    health_updated_at: datetime | None
    slo_latency_ms_p95: float
    slo_error_rate: float
    attributes: dict
    upstream_of: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class DependencyIn(BaseModel):
    upstream: str = Field(description="service that calls / depends on the downstream")
    downstream: str
    environment: str = "production"
    kind: str = "sync"
    critical: bool = True


class DependencyEdge(BaseModel):
    upstream: str
    downstream: str
    kind: str
    critical: bool


class DependencyGraph(BaseModel):
    nodes: list[ServiceOut]
    edges: list[DependencyEdge]


class BlastRadius(BaseModel):
    service: str
    direct_dependents: list[str]
    indirect_dependents: list[str]
    downstream_dependencies: list[str]
    impacted_user_facing: list[str]
    total_impacted: int


class DeploymentIn(BaseModel):
    service: str
    environment: str = "production"
    version: str = Field(min_length=1, max_length=60)
    previous_version: str | None = None
    commit_sha: str | None = Field(default=None, max_length=40)
    change_summary: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: DeploymentStatus = DeploymentStatus.SUCCEEDED
    triggered_by: str = "ci"
    attributes: dict = Field(default_factory=dict)


class DeploymentOut(BaseModel):
    id: str
    ref: str
    service: str
    environment_id: str
    version: str
    previous_version: str | None
    commit_sha: str | None
    change_summary: str
    started_at: datetime
    completed_at: datetime | None
    status: DeploymentStatus
    triggered_by: str
