"""Versioned prompt registry.

Every agent run records the prompt name + version it used (spec 69). Prompts are
also synced into the ``prompt_versions`` table on startup so runs can be audited
against the exact text that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.models import PromptVersion


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str
    notes: str = ""

    @property
    def checksum(self) -> str:
        return sha256(self.body.encode()).hexdigest()[:64]


INVESTIGATOR_V1 = Prompt(
    name="incident-investigator",
    version="v1",
    notes="Initial evidence-grounded RCA synthesis prompt.",
    body=(
        "You are Nirikshan's incident investigator, a senior SRE. You are given a "
        "structured EVIDENCE BUNDLE that was collected by audited tools (metrics, "
        "logs, traces, deployments, dependency graph, prior incidents). You may ONLY "
        "reason from this bundle. You must not assume facts that are not present.\n\n"
        "Produce ranked hypotheses for the root cause, each grounded in specific "
        "evidence ids from the bundle, then commit to the most probable root cause "
        "with a calibrated confidence (0..1). Prefer a single dominant cause; list "
        "others as contributing factors. If the evidence is insufficient, say so and "
        "return low confidence rather than guessing."
    ),
)

REMEDIATION_V1 = Prompt(
    name="remediation-agent",
    version="v1",
    notes="Safe remediation planning constrained to the action allowlist.",
    body=(
        "You are Nirikshan's remediation planner. Given an incident and its RCA, "
        "propose exactly ONE corrective action chosen from the registered safe-action "
        "allowlist. You must never propose shell commands, ad-hoc scripts, or actions "
        "outside the allowlist. Provide a rationale tied to the RCA, the expected "
        "impact, a rollback plan, and a verification plan expressed as concrete metric "
        "checks against the affected service's SLOs. Default risk posture is cautious; "
        "destructive-looking actions require human approval."
    ),
)

_REGISTRY: dict[tuple[str, str], Prompt] = {
    (p.name, p.version): p for p in (INVESTIGATOR_V1, REMEDIATION_V1)
}
_LATEST: dict[str, Prompt] = {
    "incident-investigator": INVESTIGATOR_V1,
    "remediation-agent": REMEDIATION_V1,
}


def get_prompt(name: str, version: str | None = None) -> Prompt:
    if version:
        try:
            return _REGISTRY[(name, version)]
        except KeyError:
            raise KeyError(f"unknown prompt {name}@{version}") from None
    return _LATEST[name]


def sync_prompts(db: Session) -> int:
    """Insert any prompt versions not yet persisted. Returns count added."""
    added = 0
    for p in _REGISTRY.values():
        exists = db.scalar(
            select(PromptVersion).where(
                PromptVersion.name == p.name, PromptVersion.version == p.version
            )
        )
        if exists is None:
            db.add(
                PromptVersion(
                    name=p.name, version=p.version, checksum=p.checksum, body=p.body, notes=p.notes
                )
            )
            added += 1
    if added:
        db.flush()
    return added
