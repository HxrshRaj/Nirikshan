"""Password hashing (bcrypt)."""

from __future__ import annotations

import bcrypt

_MAX = 72  # bcrypt truncation limit


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8")[:_MAX], bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:_MAX], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
