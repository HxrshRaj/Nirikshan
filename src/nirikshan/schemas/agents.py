from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from nirikshan.domain.enums import AgentKind, AgentRunStatus


class ToolCallOut(BaseModel):
    sequence: int
    tool_name: str
    arguments: dict
    ok: bool
    error: str | None
    result_summary: str
    result_rows: int
    duration_ms: float


class AgentRunSummary(BaseModel):
    id: str
    run_id: str
    kind: AgentKind
    incident_id: str | None
    status: AgentRunStatus
    provider: str
    model: str
    is_mock: bool
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: float | None
    tool_call_count: int
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    error: str | None


class AgentRunDetail(AgentRunSummary):
    prompt_name: str
    prompt_version: str
    result: dict
    audit: dict
    tool_calls: list[ToolCallOut]
