"""Post-remediation verification: compare live telemetry against the plan's checks.

A check passes when the aggregated metric over the recent window satisfies the
``op``/``target`` and, when ``compare_to_baseline`` is set, has also moved back
toward its learned baseline. Uses only stored telemetry (spec 33).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from nirikshan.catalog.service import find_service
from nirikshan.core.clock import utcnow
from nirikshan.detection.baseline import load_baseline
from nirikshan.telemetry.aggregate import compute_service_health
from nirikshan.telemetry.query import metric_series

_OPS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
}


def _measure(db: Session, check: dict) -> float | None:
    svc_name = check["service"]
    metric = check["metric"]
    if metric == "error_rate":
        svc = find_service(db, svc_name.lower())
        if not svc:
            return None
        return compute_service_health(db, svc, window_seconds=check.get("window_seconds", 300)).error_rate
    agg = check.get("agg", "avg")
    series = metric_series(
        db,
        service=svc_name.lower(),
        metric_name=metric,
        minutes=max(check.get("window_seconds", 300) // 60, 2),
        step_seconds=60,
        aggregation="p95" if agg == "p95" else "avg",
    )
    vals = [p.value for p in series.points]
    if not vals:
        return None
    return max(vals) if agg == "max" else sum(vals) / len(vals)


def run_verification(db: Session, plan: dict) -> dict:
    checks = plan.get("checks", [])
    compare_baseline = plan.get("compare_to_baseline", False)
    results = []
    passed = 0
    for check in checks:
        measured = _measure(db, check)
        op = _OPS.get(check.get("op", "lt"), _OPS["lt"])
        target = float(check.get("target", 0))
        ok = measured is not None and op(measured, target)

        baseline_ok = True
        if ok and compare_baseline and check["metric"] != "error_rate":
            svc = find_service(db, check["service"].lower())
            if svc:
                b = load_baseline(db, svc.id, check["metric"])
                if b and b.mean > 0 and measured is not None:
                    spread = max(b.std, b.ewstd, 1e-9)
                    band = max(b.p95 * 2.0, b.mean + 5 * spread)
                    baseline_ok = measured <= band
        ok = ok and baseline_ok
        results.append(
            {
                "service": check["service"],
                "metric": check["metric"],
                "agg": check.get("agg", "avg"),
                "op": check.get("op", "lt"),
                "target": target,
                "measured": round(measured, 4) if measured is not None else None,
                "ok": bool(ok),
                "baseline_ok": baseline_ok,
            }
        )
        passed += int(bool(ok))

    total = len(results)
    return {
        "passed": passed,
        "total": total,
        "success": total > 0 and passed == total,
        "checks": results,
        "evaluated_at": utcnow().isoformat(),
        "summary": f"{passed}/{total} verification checks passed",
    }
