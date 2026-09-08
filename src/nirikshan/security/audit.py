"""Audit-log helper. Records sensitive actions with actor / before / after."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.models import AuditLog

_SENSITIVE_KEYS = {"password", "password_hash", "secret", "token", "api_key", "authorization"}


def _scrub(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in data.items()
        }
    if isinstance(data, list):
        return [_scrub(v) for v in data]
    return data


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    result: str = "success",
    actor_role: str = "",
    ip: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    note: str = "",
) -> AuditLog:
    row = AuditLog(
        at=utcnow(),
        actor=actor,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        ip=ip,
        before=_scrub(before) if before else None,
        after=_scrub(after) if after else None,
        note=note[:2000],
    )
    db.add(row)
    db.flush()
    return row


def list_audit(
    db: Session,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func

    stmt = select(AuditLog).order_by(AuditLog.at.desc())
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.limit(min(limit, 500)).offset(offset)))
    return rows, total
