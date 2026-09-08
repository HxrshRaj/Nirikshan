"""Deterministic remediation planner for the mock / demo provider.

Maps an RCA category + incident context onto exactly one *registered* safe
action (never a free-form command) with a rollback and verification plan.
"""

from __future__ import annotations

from nirikshan.ai.contracts import RemediationPlan, Usage
from nirikshan.ai.cost import estimate_tokens

_RISK = {
    "rollback_demo_deployment": "MEDIUM",
    "scale_demo_service": "LOW",
    "restart_demo_service": "MEDIUM",
    "disable_demo_feature_flag": "LOW",
    "clear_demo_cache": "LOW",
}


def _verification(ctx: dict) -> dict:
    svc = ctx["service"]
    slo = ctx.get("slo", {})
    checks = [
        {"service": svc, "metric": "error_rate", "op": "lt",
         "target": round(slo.get("error_rate", 0.02), 4), "window_seconds": 300},
        {"service": svc, "metric": "request_latency_ms", "agg": "p95", "op": "lt",
         "target": round(slo.get("latency_ms_p95", 300.0) * 1.2, 1), "window_seconds": 300},
    ]
    if ctx.get("db_involved"):
        ceiling = ctx.get("db_ceiling", 100)
        checks.append({"service": svc, "metric": "database_connections", "op": "lt",
                       "target": round(ceiling * 0.75, 1), "window_seconds": 300})
    return {"checks": checks, "window_seconds": 300, "compare_to_baseline": True}


def plan(ctx: dict) -> RemediationPlan | None:
    """``ctx`` is built by the remediation agent from the incident + RCA."""
    category = ctx.get("category", "inconclusive")
    svc = ctx["service"]
    recent_deploy = ctx.get("recent_deployment")
    confidence = float(ctx.get("rca_confidence", 0.5))

    if category == "inconclusive" or confidence < 0.4:
        return None

    action = None
    params: dict = {}
    rationale = ""
    impact = ""
    rollback = ""

    if category in ("deployment_regression",) or (
        category == "database_saturation" and recent_deploy
    ):
        if not recent_deploy:
            return None
        action = "rollback_demo_deployment"
        params = {"service": svc, "to_version": recent_deploy.get("previous_version") or "previous",
                  "from_version": recent_deploy.get("version"), "deployment_ref": recent_deploy.get("ref")}
        rationale = (
            f"RCA attributes the incident to deployment {recent_deploy.get('ref')} "
            f"({recent_deploy.get('version')}). Rolling back to "
            f"{params['to_version']} removes the suspected regression."
        )
        impact = "Error rate and latency return toward baseline once the previous build is serving traffic."
        rollback = f"Re-deploy {recent_deploy.get('version')} (roll-forward) if the rollback does not improve SLIs."

    elif category == "database_saturation":
        action = "scale_demo_service"
        params = {"service": svc, "replicas_delta": 2, "connection_pool_delta": 20}
        rationale = (
            "database_connections is saturated with no implicated deployment; adding capacity and "
            "pool headroom relieves connection contention while the workload is investigated."
        )
        impact = "DB connection wait time drops; downstream latency and errors recover."
        rollback = "Scale the service and pool back to their previous values."

    elif category == "upstream_dependency_failure":
        dep = (ctx.get("unhealthy_dependencies") or [{}])[0].get("service", "dependency")
        action = "disable_demo_feature_flag"
        params = {"service": svc, "flag": f"require-{dep}", "reason": f"degraded mode while {dep} is unhealthy"}
        rationale = (
            f"The root cause is an unhealthy upstream dependency ({dep}). Enabling degraded mode "
            f"lets the service shed the hard dependency and serve reduced functionality."
        )
        impact = f"Requests stop blocking on {dep}; caller error rate falls even though {dep} is still impaired."
        rollback = f"Re-enable the 'require-{dep}' flag once {dep} is healthy."

    elif category == "traffic_overload":
        action = "scale_demo_service"
        params = {"service": svc, "replicas_delta": 3}
        rationale = "Load exceeds current capacity; horizontal scale-out restores headroom."
        impact = "Queue depth drains and latency returns to baseline."
        rollback = "Scale back to the previous replica count after traffic subsides."

    elif category == "resource_saturation":
        action = "restart_demo_service"
        params = {"service": svc, "strategy": "rolling"}
        rationale = "Resource saturation with a suspected leak; a rolling restart reclaims memory/handles safely."
        impact = "CPU/memory return to baseline immediately after instances cycle."
        rollback = "No rollback required; restart is non-destructive. Scale out if saturation recurs."
    else:
        return None

    risk = _RISK.get(action, "MEDIUM")
    verification = _verification(ctx)
    usage = Usage(
        input_tokens=estimate_tokens(str(ctx)),
        output_tokens=estimate_tokens(rationale + impact + rollback + str(verification)),
    )
    return RemediationPlan(
        action_name=action,
        parameters=params,
        rationale="[Demo / Mock Provider] " + rationale,
        risk=risk,
        expected_impact=impact,
        rollback_plan=rollback,
        verification=verification,
        confidence=round(min(0.9, confidence), 3),
        usage=usage,
        is_mock=True,
        provider="mock",
        model="mock-sre-1",
        alternatives=_alternatives(category, svc),
        warnings=[],
    )


def _alternatives(category: str, svc: str) -> list[dict]:
    if category == "deployment_regression":
        return [{"action_name": "disable_demo_feature_flag",
                 "parameters": {"service": svc, "flag": "new-behavior"},
                 "note": "if the regression is behind a flag, disabling it is lower-risk than a full rollback"}]
    if category == "database_saturation":
        return [{"action_name": "restart_demo_service", "parameters": {"service": svc},
                 "note": "restart to drop leaked/idle connections if scaling is not enough"}]
    return []
