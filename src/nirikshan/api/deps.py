"""Shared FastAPI dependencies: DB session, current user, RBAC, rate limiting."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from nirikshan.core.db import session_factory
from nirikshan.core.errors import AuthError, PermissionError_, RateLimitError
from nirikshan.domain.enums import Role
from nirikshan.models import User
from nirikshan.security.ratelimit import RateLimit
from nirikshan.security.tokens import decode_token


def get_db() -> Iterator[Session]:
    """Request-scoped session; commits on success, rolls back on error."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, expected_type="access")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise AuthError("user not found or inactive")
    return user


def optional_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User | None:
    try:
        if not authorization:
            return None
        return current_user(db=db, authorization=authorization)
    except AuthError:
        return None


def require_role(minimum: Role):
    def _dep(user: User = Depends(current_user)) -> User:
        if Role(user.role).rank < minimum.rank:
            raise PermissionError_(
                f"role {user.role} is insufficient; requires {minimum.value} or higher"
            )
        return user

    return _dep


def ingest_guard(
    x_ingest_token: str | None = Header(default=None),
) -> None:
    """Telemetry ingestion auth. Open when NIRIKSHAN_INGEST_TOKEN is unset (demo);
    otherwise requires a matching ``X-Ingest-Token`` header (constant-time compare)."""
    import secrets

    from nirikshan.core.config import get_settings

    expected = get_settings().ingest_token
    if not expected:
        return
    if not x_ingest_token or not secrets.compare_digest(x_ingest_token, expected):
        raise AuthError("invalid or missing X-Ingest-Token")


def rate_limit(name: str):
    limiter = RateLimit(name)

    def _dep(request: Request, user: User | None = Depends(optional_user)) -> None:
        identity = user.id if user else client_ip(request)
        allowed, remaining, retry = limiter.check(f"{name}:{identity}")
        request.state.rate_remaining = remaining
        if not allowed:
            raise RateLimitError(
                f"rate limit exceeded for {name}", details={"retry_after_seconds": retry}
            )

    return _dep
