"""Incident memory: distil resolved incidents into a retrievable knowledge base.

On close, an incident is summarised into a ``HistoricalIncident`` document with
an embedding vector (via the abstracted embedding provider - local hash fallback
by default). The investigator retrieves the top-k most similar past incidents as
supporting context (spec 35, 36).
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.logging import get_logger
from nirikshan.models import HistoricalIncident, Incident

log = get_logger("incidents.memory")


def _doc_text(inc: Incident) -> str:
    parts = [
        inc.title,
        f"service: {inc.service_name}",
        f"severity: {inc.severity}",
        f"summary: {inc.summary}",
        f"root cause: {inc.root_cause}",
        "contributing factors: " + "; ".join(inc.contributing_factors or []),
        "recommended actions: " + "; ".join(inc.recommended_actions or []),
        "affected services: " + ", ".join(inc.affected_services or []),
    ]
    return "\n".join(p for p in parts if p and not p.endswith(": "))


def archive_incident(db: Session, inc: Incident) -> HistoricalIncident:
    from nirikshan.ai.providers import get_embedding_provider

    existing = db.scalar(
        select(HistoricalIncident).where(HistoricalIncident.incident_id == inc.id)
    )
    doc = _doc_text(inc)
    provider = get_embedding_provider()
    vector = provider.embed([doc])[0]

    duration_minutes = 0.0
    if inc.resolved_at and inc.detected_at:
        duration_minutes = round((inc.resolved_at - inc.detected_at).total_seconds() / 60.0, 1)

    if existing is None:
        existing = HistoricalIncident(incident_id=inc.id, incident_ref=inc.ref)
        db.add(existing)
    existing.title = inc.title
    existing.service_name = inc.service_name
    existing.severity = inc.severity
    existing.resolved_at = inc.resolved_at or utcnow()
    existing.duration_minutes = duration_minutes
    existing.summary = inc.summary
    existing.root_cause = inc.root_cause or "not recorded"
    existing.resolution = inc.summary.split("Resolution:", 1)[-1].strip() if "Resolution:" in inc.summary else ""
    existing.remediation = "; ".join(inc.recommended_actions or [])
    existing.affected_services = inc.affected_services or []
    existing.tags = _tags(inc)
    existing.embedding = list(map(float, vector))
    existing.embedding_model = provider.model
    existing.doc_text = doc
    db.flush()
    log.info("incident.archived", ref=inc.ref)
    return existing


def _tags(inc: Incident) -> list[str]:
    text = f"{inc.title} {inc.root_cause} {inc.summary}".lower()
    vocab = {
        "database": ["database", "connection pool", "db pool", "postgres"],
        "deployment": ["deployment", "rollback", "regression", "version"],
        "latency": ["latency", "slow", "timeout"],
        "traffic": ["traffic", "spike", "load", "queue"],
        "dependency": ["dependency", "upstream", "downstream", "outage"],
        "memory": ["memory", "oom", "leak"],
        "cpu": ["cpu", "saturation"],
    }
    return sorted(t for t, kws in vocab.items() if any(k in text for k in kws))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def similar_incidents(
    db: Session, *, query_text: str, exclude_incident_id: str | None = None, k: int = 3
) -> list[dict]:
    from nirikshan.ai.providers import get_embedding_provider

    rows = list(db.scalars(select(HistoricalIncident)))
    if not rows:
        return []
    provider = get_embedding_provider()
    qvec = np.asarray(provider.embed([query_text])[0], dtype=float)
    scored: list[tuple[float, HistoricalIncident]] = []
    for r in rows:
        if exclude_incident_id and r.incident_id == exclude_incident_id:
            continue
        if not r.embedding:
            continue
        sim = _cosine(qvec, np.asarray(r.embedding, dtype=float))
        scored.append((sim, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    out = []
    for sim, r in scored[:k]:
        out.append(
            {
                "incident_ref": r.incident_ref,
                "title": r.title,
                "service": r.service_name,
                "severity": r.severity,
                "similarity": round(sim, 3),
                "root_cause": r.root_cause,
                "remediation": r.remediation,
                "duration_minutes": r.duration_minutes,
                "tags": r.tags,
            }
        )
    return out
