"""Deterministic rule-based SRE reasoner used by the *mock / demo* provider.

This is NOT a language model. It performs structured pattern analysis over the
**curated evidence bundle** that the investigator agent assembled from real
tool calls, and produces ranked hypotheses + an RCA. It never invents metrics,
logs, deployments or incidents - every claim references an evidence id that the
orchestrator actually collected.

Output from this module is always labelled ``is_mock=True`` and surfaced in the
UI as "Demo / Mock Provider" so it is never mistaken for a production model.
"""

from __future__ import annotations

from nirikshan.ai.contracts import AnalysisResult, Hypothesis, Usage
from nirikshan.ai.cost import estimate_tokens

_CATEGORY_ACTIONS = {
    "database_saturation": [
        "Increase the database connection pool ceiling for the affected service",
        "Roll back the most recent deployment if it raised connection concurrency",
        "Add short-lived read replicas / PgBouncer pooling to relieve pressure",
    ],
    "deployment_regression": [
        "Roll back the suspect deployment to the previous known-good version",
        "Freeze further deploys to the service until the incident is resolved",
        "Bisect the change set for the regression once traffic recovers",
    ],
    "upstream_dependency_failure": [
        "Page the owning team for the unhealthy dependency",
        "Enable the service's degraded-mode / circuit breaker for that dependency",
        "Fail over to a replica / secondary for the dependency if available",
    ],
    "traffic_overload": [
        "Scale out the affected service horizontally",
        "Enable request shedding / rate limiting at the edge for non-critical traffic",
        "Increase worker concurrency and queue consumers to drain backlog",
    ],
    "resource_saturation": [
        "Scale the service vertically or horizontally to add headroom",
        "Investigate the change in workload that raised CPU/memory",
        "Restart instances showing runaway memory if a leak is suspected",
    ],
    "inconclusive": [
        "Continue manual investigation with the collected evidence",
        "Acknowledge the incident and monitor key SLIs for the next 15 minutes",
    ],
}


def _mk(cat: str, title: str, rationale: str, conf: float, ev: list[str]) -> Hypothesis:
    return Hypothesis(
        title=title, category=cat, rationale=rationale, confidence=round(conf, 3),
        supporting_evidence_ids=ev,
    )


def _confidence_for(support: int) -> float:
    return {0: 0.30, 1: 0.46, 2: 0.68, 3: 0.82}.get(support, 0.91)


def analyze(bundle: dict) -> AnalysisResult:
    metrics = {m["metric"]: m for m in bundle.get("metrics", [])}
    anomalies = {a["metric"]: a for a in bundle.get("anomalies", [])}
    logs = bundle.get("logs", {})
    deploys = bundle.get("deployments", [])
    deps = bundle.get("dependencies", {})
    priors = bundle.get("prior_incidents", [])

    hypotheses: list[Hypothesis] = []
    factors: list[str] = []

    def anom(metric: str) -> bool:
        a = anomalies.get(metric)
        return bool(a and a.get("direction") == "high")

    # ---- signal: recent deployment shortly before detection -----------------
    recent_deploy = None
    for d in deploys:
        mins = d.get("minutes_before_incident")
        if mins is not None and -2 <= mins <= 30:
            recent_deploy = d
            break

    # ---- signal: unhealthy dependency -------------------------------------
    unhealthy_deps = deps.get("unhealthy_dependencies", [])

    # ---- signal: DB connection pressure ---------------------------------
    db_metric = metrics.get("database_connections")
    db_pressure = anom("database_connections") or (
        db_metric and db_metric.get("current") and db_metric.get("baseline_mean")
        and db_metric["current"] >= 1.8 * max(db_metric["baseline_mean"], 1)
    )
    conn_logs = any(
        kw in (logs.get("top_patterns_text") or "").lower()
        for kw in ("connection pool", "acquire connection", "too many clients", "timeout acquiring", "pool exhausted")
    )

    latency_up = anom("request_latency_ms")
    errors_up = anom("error_rate") or anom("error_count") or (logs.get("error_count", 0) > 20)
    traffic_up = anom("request_count")
    queue_up = anom("queue_depth")
    cpu_up = anom("cpu_usage")
    mem_up = anom("memory_usage")

    # =====================================================================
    # Hypothesis A: database connection pool exhaustion
    # =====================================================================
    if db_pressure:
        ev = ["metric:database_connections"]
        support = 1
        rationale_bits = ["database_connections is well above its learned baseline"]
        if latency_up:
            ev.append("metric:request_latency_ms"); support += 1
            rationale_bits.append("request latency rose in lock-step")
        if errors_up:
            ev.append("metric:error_rate"); support += 1
            rationale_bits.append("error rate increased")
        if conn_logs:
            ev.append("logs:connection_errors"); support += 1
            rationale_bits.append("logs show connection-acquisition failures")
        if recent_deploy:
            ev.append(f"deploy:{recent_deploy['ref']}"); support += 1
            rationale_bits.append(
                f"deployment {recent_deploy['ref']} landed "
                f"{recent_deploy['minutes_before_incident']:.0f} min before detection and may have raised DB concurrency"
            )
            factors.append(f"Deployment {recent_deploy['ref']} ({recent_deploy.get('version')})")
        conf = _confidence_for(support)
        hypotheses.append(
            _mk("database_saturation", "Database connection pool exhaustion",
                "; ".join(rationale_bits) + ".", conf, ev)
        )

    # =====================================================================
    # Hypothesis B: deployment regression
    # =====================================================================
    if recent_deploy and (errors_up or latency_up):
        ev = [f"deploy:{recent_deploy['ref']}"]
        support = 1
        bits = [
            f"deployment {recent_deploy['ref']} ({recent_deploy.get('version')}) completed "
            f"{recent_deploy['minutes_before_incident']:.0f} min before the incident was detected"
        ]
        if errors_up:
            ev.append("metric:error_rate"); support += 1
            bits.append("error rate climbed after the deploy")
        if latency_up:
            ev.append("metric:request_latency_ms"); support += 1
            bits.append("latency climbed after the deploy")
        if logs.get("error_count", 0) > 20:
            ev.append("logs:error_sample"); support += 1
            bits.append(f"{logs['error_count']} error logs in the window")
        conf = _confidence_for(support)
        # if there is a strong DB story, the deploy is more likely a contributing factor
        if db_pressure:
            conf = min(conf, 0.74)
        hypotheses.append(
            _mk("deployment_regression",
                f"Regression introduced by deployment {recent_deploy['ref']}",
                "; ".join(bits) + ".", conf, ev)
        )

    # =====================================================================
    # Hypothesis C: upstream dependency failure
    # =====================================================================
    if unhealthy_deps:
        names = ", ".join(d["service"] for d in unhealthy_deps)
        ev = [f"dep:unhealthy:{unhealthy_deps[0]['service']}"]
        support = 1 + (1 if latency_up else 0) + (1 if errors_up else 0)
        bits = [f"hard dependency/dependencies unhealthy: {names}"]
        if latency_up:
            ev.append("metric:request_latency_ms"); bits.append("caller latency elevated")
        if errors_up:
            ev.append("metric:error_rate"); bits.append("caller error rate elevated")
        conf = _confidence_for(support)
        if unhealthy_deps[0].get("kind") == "datastore":
            conf = min(conf + 0.05, 0.94)
        hypotheses.append(
            _mk("upstream_dependency_failure",
                f"Upstream dependency failure ({names})",
                "; ".join(bits) + ".", conf, ev)
        )
        factors.append(f"Unhealthy dependency: {names}")

    # =====================================================================
    # Hypothesis D: traffic-driven overload
    # =====================================================================
    if (traffic_up or queue_up) and not recent_deploy and not unhealthy_deps:
        ev = []
        support = 0
        bits = []
        if traffic_up:
            ev.append("metric:request_count"); support += 1
            bits.append("request volume spiked above baseline")
        if queue_up:
            ev.append("metric:queue_depth"); support += 1
            bits.append("queue depth is backing up")
        if latency_up:
            ev.append("metric:request_latency_ms"); support += 1
            bits.append("latency rose with load")
        hypotheses.append(
            _mk("traffic_overload", "Traffic-driven overload / queue saturation",
                "; ".join(bits) + ".", _confidence_for(support), ev)
        )

    # =====================================================================
    # Hypothesis E: resource saturation
    # =====================================================================
    if cpu_up or mem_up:
        ev = []
        bits = []
        if cpu_up:
            ev.append("metric:cpu_usage"); bits.append("CPU usage anomalous")
        if mem_up:
            ev.append("metric:memory_usage"); bits.append("memory usage anomalous")
        support = len(ev) + (1 if latency_up else 0)
        conf = _confidence_for(support)
        if recent_deploy or unhealthy_deps or db_pressure:
            conf = min(conf, 0.55)
        hypotheses.append(
            _mk("resource_saturation", "Compute resource saturation",
                "; ".join(bits) + ".", conf, ev)
        )

    # ---- prior incident support ----------------------------------------
    if priors and hypotheses:
        top = priors[0]
        if top.get("similarity", 0) >= 0.55:
            hypotheses[0].supporting_evidence_ids.append(f"prior:{top['incident_ref']}")
            hypotheses[0].confidence = round(min(0.95, hypotheses[0].confidence + 0.04), 3)
            factors.append(
                f"Similar past incident {top['incident_ref']} ({top.get('root_cause','')[:80]})"
            )

    # ---- fallback -----------------------------------------------------
    if not hypotheses:
        hypotheses.append(
            _mk("inconclusive", "Root cause not conclusively isolated",
                "Elevated error/latency signals were observed but no single dominant cause "
                "(deployment, dependency, DB, traffic, resource) reached the evidence threshold.",
                0.32, [k for k in ("metric:request_latency_ms", "metric:error_rate") if k.split(":")[1] in metrics])
        )

    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    top = hypotheses[0]

    grounded = sorted({e for h in hypotheses for e in h.supporting_evidence_ids})
    actions = _CATEGORY_ACTIONS.get(top.category, _CATEGORY_ACTIONS["inconclusive"])

    summary = (
        f"[Demo / Mock Provider] Structured analysis of {len(bundle.get('metrics', []))} metric series, "
        f"{logs.get('error_count', 0)} error logs, {len(deploys)} recent deployments and "
        f"{len(bundle.get('anomalies', []))} anomalies. Most probable cause: {top.title} "
        f"(confidence {top.confidence:.2f})."
    )

    usage = Usage(
        input_tokens=estimate_tokens(str(bundle)),
        output_tokens=estimate_tokens(summary + " ".join(a for a in actions)),
    )

    return AnalysisResult(
        root_cause=top.title,
        confidence=top.confidence,
        summary=summary,
        hypotheses=hypotheses,
        contributing_factors=sorted(set(factors)),
        recommended_actions=list(actions),
        usage=usage,
        is_mock=True,
        provider="mock",
        model="mock-sre-1",
        grounded_evidence_ids=grounded,
        warnings=[] if top.category != "inconclusive" else ["Low-confidence result: evidence did not isolate a single cause."],
    )
