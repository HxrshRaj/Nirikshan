"""LLM + embedding provider abstraction.

Providers
---------
* ``mock``   - deterministic rule-based reasoner (``mock_reasoner`` / ``mock_planner``).
               Always available; output labelled ``is_mock=True``.
* ``openai`` - OpenAI-compatible ``/chat/completions`` (JSON response).
* ``groq``   - same wire format, different ``base_url`` / models.

If a remote provider is selected but no API key is configured, the factory
transparently falls back to ``mock`` so the platform never hard-fails on a
missing optional credential (spec 64, 83).

The agents call ``analyze()`` / ``plan_remediation()`` with an already-curated
evidence bundle - the model never receives raw database access.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from hashlib import blake2b
from itertools import pairwise

import httpx

from nirikshan.ai import mock_planner, mock_reasoner
from nirikshan.ai.contracts import AnalysisResult, Hypothesis, RemediationPlan, Usage
from nirikshan.ai.cost import estimate_tokens
from nirikshan.core.config import get_settings
from nirikshan.core.errors import ProviderUnavailable
from nirikshan.core.logging import get_logger

log = get_logger("ai.providers")

_ALLOWED_ACTIONS = {
    "rollback_demo_deployment",
    "scale_demo_service",
    "restart_demo_service",
    "disable_demo_feature_flag",
    "clear_demo_cache",
}


# --------------------------------------------------------------------------- #
# LLM providers
# --------------------------------------------------------------------------- #
class LLMProvider(ABC):
    name: str = "base"
    model: str = ""
    is_mock: bool = True

    @abstractmethod
    def analyze(self, bundle: dict, *, prompt: str) -> AnalysisResult: ...

    @abstractmethod
    def plan_remediation(self, context: dict, *, prompt: str) -> RemediationPlan | None: ...


class MockProvider(LLMProvider):
    name = "mock"
    is_mock = True

    def __init__(self, model: str = "mock-sre-1"):
        self.model = model

    def analyze(self, bundle: dict, *, prompt: str) -> AnalysisResult:
        t0 = time.perf_counter()
        result = mock_reasoner.analyze(bundle)
        result.usage.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return result

    def plan_remediation(self, context: dict, *, prompt: str) -> RemediationPlan | None:
        t0 = time.perf_counter()
        plan = mock_planner.plan(context)
        if plan is not None:
            plan.usage.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return plan


_ANALYSIS_SCHEMA_HINT = """
Return ONLY minified JSON, no prose, matching:
{"root_cause": str, "confidence": number 0..1, "summary": str,
 "contributing_factors": [str], "recommended_actions": [str],
 "hypotheses": [{"title": str, "category": one of
   ["database_saturation","deployment_regression","upstream_dependency_failure",
    "traffic_overload","resource_saturation","inconclusive"],
   "rationale": str, "confidence": number 0..1,
   "supporting_evidence_ids": [str]}]}
Every supporting_evidence_id MUST be an id present in the provided evidence bundle.
Do not invent metrics, logs, deployments, or incidents.
"""

_PLAN_SCHEMA_HINT = f"""
Return ONLY minified JSON matching:
{{"action_name": one of {sorted(_ALLOWED_ACTIONS)},
  "parameters": object, "rationale": str, "risk": one of ["LOW","MEDIUM","HIGH"],
  "expected_impact": str, "rollback_plan": str,
  "verification": {{"checks": [object], "window_seconds": int}},
  "confidence": number 0..1}}
Only the listed action_name values are permitted. Never emit shell commands.
"""


class RemoteOpenAICompatProvider(LLMProvider):
    """Works with OpenAI and Groq (`/chat/completions`, JSON mode)."""

    is_mock = False

    def __init__(self, *, name: str, model: str, api_key: str, base_url: str, timeout: int):
        self.name = name
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _chat(self, system: str, user: str) -> tuple[str, Usage]:
        t0 = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.name} request failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(f"{self.name} returned an unexpected shape") from exc

        u = data.get("usage", {})
        usage = Usage(
            input_tokens=int(u.get("prompt_tokens", estimate_tokens(system + user))),
            output_tokens=int(u.get("completion_tokens", estimate_tokens(content))),
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
        return content, usage

    def analyze(self, bundle: dict, *, prompt: str) -> AnalysisResult:
        system = prompt + "\n" + _ANALYSIS_SCHEMA_HINT
        user = "EVIDENCE BUNDLE:\n" + json.dumps(bundle, default=str)
        content, usage = self._chat(system, user)
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"{self.name} returned malformed JSON") from exc
        return _validate_analysis(raw, bundle, usage, provider=self.name, model=self.model)

    def plan_remediation(self, context: dict, *, prompt: str) -> RemediationPlan | None:
        system = prompt + "\n" + _PLAN_SCHEMA_HINT
        user = "INCIDENT + RCA CONTEXT:\n" + json.dumps(context, default=str)
        content, usage = self._chat(system, user)
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"{self.name} returned malformed JSON") from exc
        return _validate_plan(raw, context, usage, provider=self.name, model=self.model)


# --------------------------------------------------------------------------- #
# Output validation / guardrails (spec 25, 38, 65)
# --------------------------------------------------------------------------- #
def _collect_evidence_ids(bundle: dict) -> set[str]:
    ids: set[str] = set()
    for m in bundle.get("metrics", []):
        ids.add(f"metric:{m['metric']}")
    for a in bundle.get("anomalies", []):
        ids.add(f"anomaly:{a['metric']}")
    for d in bundle.get("deployments", []):
        ids.add(f"deploy:{d['ref']}")
    for p in bundle.get("prior_incidents", []):
        ids.add(f"prior:{p['incident_ref']}")
    for u in bundle.get("dependencies", {}).get("unhealthy_dependencies", []):
        ids.add(f"dep:unhealthy:{u['service']}")
    ids.update({"logs:error_sample", "logs:connection_errors", "logs:top_patterns"})
    return ids


def _validate_analysis(
    raw: dict, bundle: dict, usage: Usage, *, provider: str, model: str
) -> AnalysisResult:
    valid_ids = _collect_evidence_ids(bundle)
    warnings: list[str] = []
    hyps: list[Hypothesis] = []
    for h in raw.get("hypotheses", []) or []:
        cited = [e for e in (h.get("supporting_evidence_ids") or []) if e in valid_ids]
        dropped = set(h.get("supporting_evidence_ids") or []) - set(cited)
        if dropped:
            warnings.append(f"dropped uncited evidence refs from hypothesis {h.get('title')!r}: {sorted(dropped)}")
        conf = _clamp(h.get("confidence", 0.3))
        if not cited and conf > 0.5:
            conf = 0.5
            warnings.append(f"capped confidence for ungrounded hypothesis {h.get('title')!r}")
        hyps.append(
            Hypothesis(
                title=str(h.get("title", "unnamed"))[:200],
                category=str(h.get("category", "inconclusive")),
                rationale=str(h.get("rationale", ""))[:2000],
                confidence=conf,
                supporting_evidence_ids=cited,
            )
        )
    if not hyps:
        raise ProviderUnavailable(f"{provider} produced no usable hypotheses")
    hyps.sort(key=lambda x: x.confidence, reverse=True)
    top = hyps[0]
    grounded = sorted({e for h in hyps for e in h.supporting_evidence_ids})
    return AnalysisResult(
        root_cause=str(raw.get("root_cause") or top.title)[:2000],
        confidence=_clamp(raw.get("confidence", top.confidence)),
        summary=str(raw.get("summary", ""))[:4000],
        hypotheses=hyps,
        contributing_factors=[str(x)[:400] for x in (raw.get("contributing_factors") or [])][:8],
        recommended_actions=[str(x)[:400] for x in (raw.get("recommended_actions") or [])][:8],
        usage=usage,
        is_mock=False,
        provider=provider,
        model=model,
        grounded_evidence_ids=grounded,
        warnings=warnings,
    )


def _validate_plan(
    raw: dict, context: dict, usage: Usage, *, provider: str, model: str
) -> RemediationPlan | None:
    action = str(raw.get("action_name", "")).strip()
    if action not in _ALLOWED_ACTIONS:
        raise ProviderUnavailable(
            f"{provider} proposed disallowed action {action!r}; refusing (allowlist only)"
        )
    risk = str(raw.get("risk", "MEDIUM")).upper()
    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        risk = "MEDIUM"
    params = raw.get("parameters") or {}
    if not isinstance(params, dict):
        raise ProviderUnavailable(f"{provider} plan parameters must be an object")
    verification = raw.get("verification") or {}
    if not isinstance(verification, dict) or "checks" not in verification:
        verification = mock_planner._verification(context)
    return RemediationPlan(
        action_name=action,
        parameters=params,
        rationale=str(raw.get("rationale", ""))[:2000],
        risk=risk,
        expected_impact=str(raw.get("expected_impact", ""))[:1000],
        rollback_plan=str(raw.get("rollback_plan", ""))[:1000],
        verification=verification,
        confidence=_clamp(raw.get("confidence", 0.5)),
        usage=usage,
        is_mock=False,
        provider=provider,
        model=model,
    )


def _clamp(v, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return round(max(lo, min(hi, float(v))), 3)
    except (TypeError, ValueError):
        return lo


# --------------------------------------------------------------------------- #
# Embedding providers
# --------------------------------------------------------------------------- #
class EmbeddingProvider(ABC):
    model: str = "base"

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, dependency-free embedding.

    Hashed bag-of-token-bigrams projected into a fixed-dim unit vector. Not
    semantically rich, but stable and good enough for "have we seen an incident
    like this before" retrieval in dev / offline / CI (spec 36, 83).
    """

    def __init__(self, dim: int = 256, model: str = "local-hash-256"):
        self.dim = dim
        self.model = model

    def _vec(self, text: str) -> list[float]:
        import math

        tokens = [t for t in _normalize(text).split() if t]
        grams = tokens + [f"{a}_{b}" for a, b in pairwise(tokens)]
        v = [0.0] * self.dim
        for g in grams:
            hv = blake2b(g.encode(), digest_size=8).digest()
            idx = int.from_bytes(hv[:4], "little") % self.dim
            sign = 1.0 if hv[4] & 1 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    is_mock = False

    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: int = 30):
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = httpx.post(
                f"{self._base}/embeddings",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self.model, "input": texts},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return [row["embedding"] for row in data["data"]]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderUnavailable(f"embedding request failed: {exc}") from exc


def _normalize(text: str) -> str:
    return "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in text)


# --------------------------------------------------------------------------- #
# Factories
# --------------------------------------------------------------------------- #
_OPENAI_BASE = "https://api.openai.com/v1"
_GROQ_BASE = "https://api.groq.com/openai/v1"


def get_llm_provider() -> LLMProvider:
    s = get_settings()
    effective = s.llm_effective_provider
    if effective == "mock":
        return MockProvider(model=s.llm_model if s.llm_provider == "mock" else "mock-sre-1")
    base = s.llm_base_url or (_GROQ_BASE if effective == "groq" else _OPENAI_BASE)
    try:
        return RemoteOpenAICompatProvider(
            name=effective,
            model=s.llm_model,
            api_key=s.llm_api_key or "",
            base_url=base,
            timeout=s.llm_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("llm.provider_init_failed", provider=effective, error=str(exc))
        return MockProvider()


def get_embedding_provider() -> EmbeddingProvider:
    s = get_settings()
    if s.embedding_provider == "openai" and s.llm_api_key:
        base = s.llm_base_url or _OPENAI_BASE
        try:
            return OpenAIEmbeddingProvider(
                model=s.embedding_model, api_key=s.llm_api_key, base_url=base
            )
        except Exception:  # pragma: no cover
            pass
    return LocalHashEmbeddingProvider(dim=s.embedding_dim, model=s.embedding_model)
