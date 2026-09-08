"""AI agent-run bookkeeping: runs, tool calls, prompt versions, LLM call ledger."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nirikshan.domain.enums import AgentRunStatus
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class PromptVersion(UUIDPk, Timestamps, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (Index("ix_prompt_name_version", "name", "version", unique=True),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)  # incident-investigator
    version: Mapped[str] = mapped_column(String(20), nullable=False)  # v1, v2
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class AgentRun(UUIDPk, Timestamps, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_incident", "incident_id"),
        Index("ix_agent_runs_kind_status", "kind", "status"),
    )

    run_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # investigator|remediation
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=AgentRunStatus.CREATED.value, nullable=False
    )
    prompt_name: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    model: Mapped[str] = mapped_column(String(60), default="")
    is_mock: Mapped[bool] = mapped_column(default=True)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[float | None] = mapped_column(Float)

    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # Full structured audit trail (tools called, inputs/outputs, hypotheses...).
    audit: Mapped[dict] = mapped_column(JSON, default=dict)

    tool_calls: Mapped[list[AgentToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentToolCall.sequence"
    )


class AgentToolCall(UUIDPk, Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (Index("ix_tool_calls_run_seq", "agent_run_id", "sequence"),)

    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    result_rows: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    run: Mapped[AgentRun] = relationship(back_populates="tool_calls")


class LLMCall(UUIDPk, Base):
    """Per-request ledger for cost / latency observability. Never stores secrets."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_run", "agent_run_id"),)

    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    incident_id: Mapped[str | None] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(48), default="")
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    is_mock: Mapped[bool] = mapped_column(default=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
