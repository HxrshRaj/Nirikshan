"""Domain error types and the canonical API error envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class NirikshanError(Exception):
    """Base class for expected, translatable domain errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(NirikshanError):
    status_code = 404
    code = "not_found"


class ConflictError(NirikshanError):
    status_code = 409
    code = "conflict"


class ValidationFailure(NirikshanError):
    status_code = 422
    code = "validation_error"


class AuthError(NirikshanError):
    status_code = 401
    code = "unauthorized"


class PermissionError_(NirikshanError):
    status_code = 403
    code = "forbidden"


class RateLimitError(NirikshanError):
    status_code = 429
    code = "rate_limited"


class PolicyViolation(NirikshanError):
    status_code = 403
    code = "policy_violation"


class ProviderUnavailable(NirikshanError):
    status_code = 503
    code = "provider_unavailable"


class StateTransitionError(NirikshanError):
    status_code = 409
    code = "invalid_state_transition"


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
