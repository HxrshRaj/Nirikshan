"""Token estimation and cost lookup for AI operational metrics (spec 67)."""

from __future__ import annotations

import math

# USD per 1M tokens (input, output). Approximate public list prices; used only
# for operational estimates, never billed. Mock provider is free.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "mock-sre-1": (0.0, 0.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}
_DEFAULT_PRICE = (0.50, 1.50)


def estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token heuristic; good enough for dashboards."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICE_TABLE.get(model, _DEFAULT_PRICE)
    return round((input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout, 6)
