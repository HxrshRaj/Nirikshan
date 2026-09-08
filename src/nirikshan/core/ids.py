"""Human-friendly identifier helpers.

Database primary keys are UUID strings; on top of those we mint readable
reference codes (``INC-1042``, ``ALR-3391``, ``DEP-ከ`` ... etc.) that engineers
actually type and paste into chat.
"""

from __future__ import annotations

import secrets
import uuid

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no ambiguous 0/O/1/I


def new_uuid() -> str:
    return str(uuid.uuid4())


def short_token(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def run_id() -> str:
    return "run_" + short_token(12).lower()
