"""JWT access / refresh token minting and verification."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import jwt

from nirikshan.core.clock import utcnow
from nirikshan.core.config import get_settings
from nirikshan.core.errors import AuthError

_ALGO = "HS256"


def _encode(payload: dict[str, Any], ttl_minutes: int, token_type: str) -> str:
    s = get_settings()
    now = utcnow()
    body = {
        **payload,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": "nirikshan",
    }
    return jwt.encode(body, s.secret_key, algorithm=_ALGO)


def create_access_token(*, user_id: str, email: str, role: str) -> tuple[str, int]:
    s = get_settings()
    ttl = s.access_token_ttl_minutes
    return _encode({"sub": user_id, "email": email, "role": role}, ttl, "access"), ttl * 60


def create_refresh_token(*, user_id: str) -> str:
    s = get_settings()
    return _encode({"sub": user_id}, s.refresh_token_ttl_minutes, "refresh")


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[_ALGO], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise AuthError(f"expected {expected_type} token")
    return payload
