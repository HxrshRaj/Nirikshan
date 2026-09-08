"""Remediation lifecycle: proposed action -> approval -> execution -> verification."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nirikshan.domain.enums import RemediationStatus, RiskLevel
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class RemediationAction(UUIDPk, Timestamps, Base):
    __tablename__ = "remediation_actions"
    __table_args__ = (Index("ix_remediation_incident_status", "incident_id", "status"),)

    ref: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    proposed_by_run_id: Mapped[str | None] = mapped_column(String(36), index=True)

    action_name: Mapped[str] = mapped_column(String(60), nullable=False)  # registry key
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String(8), default=RiskLevel.MEDIUM.value)
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    rollback_plan: Mapped[str] = mapped_column(Text, default="")
    verification_plan: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(
        String(20), default=RemediationStatus.PROPOSED.value, nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), default="APPROVAL_REQUIRED")
    policy_findings: Mapped[list] = mapped_column(JSON, default=list)
    is_reversible: Mapped[bool] = mapped_column(default=True)

    approvals: Mapped[list[RemediationApproval]] = relationship(
        back_populates="action", cascade="all, delete-orphan"
    )
    executions: Mapped[list[RemediationExecution]] = relationship(
        back_populates="action", cascade="all, delete-orphan", order_by="RemediationExecution.created_at"
    )


class RemediationApproval(UUIDPk, Base):
    __tablename__ = "remediation_approvals"

    action_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(12), nullable=False)  # approved|rejected
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(24), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    action: Mapped[RemediationAction] = relationship(back_populates="approvals")


class RemediationExecution(UUIDPk, Base):
    __tablename__ = "remediation_executions"

    action_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(12), default="apply")  # apply|rollback
    actor: Mapped[str] = mapped_column(String(120), default="system")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ok: Mapped[bool] = mapped_column(default=False)
    result: Mapped[str] = mapped_column(String(20), default="pending")
    before_state: Mapped[dict] = mapped_column(JSON, default=dict)
    after_state: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    action: Mapped[RemediationAction] = relationship(back_populates="executions")
