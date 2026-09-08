"""`nirikshan-demo` -> seed the demo environment and drive scenarios from the CLI."""

from __future__ import annotations

import argparse
import json

from nirikshan.core.config import get_settings
from nirikshan.core.db import create_all, init_engine, session_scope
from nirikshan.core.logging import configure_logging


def _seed() -> dict:
    from nirikshan.ai.prompts import sync_prompts
    from nirikshan.demo.generator import generate
    from nirikshan.demo.topology import ensure_topology
    from nirikshan.security.users import ensure_bootstrap_admin, seed_demo_users

    with session_scope() as db:
        sync_prompts(db)
        ensure_bootstrap_admin(db)
        services = ensure_topology(db)
        info = generate(db, scenario=None)
        seed_demo_users(db)
    return {"services": len(services), "telemetry": info}


def main() -> None:
    parser = argparse.ArgumentParser(prog="nirikshan-demo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="create topology + baseline telemetry + demo users")
    sp = sub.add_parser("scenario", help="seed + run a fault scenario end-to-end")
    sp.add_argument("key", help="scenario key (db-exhaustion, deploy-regression, ...)")
    sp.add_argument("--remediate", action="store_true", help="also drive approval + remediation + verify")
    sub.add_parser("list", help="list available scenarios")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)
    create_all()

    if args.cmd == "list":
        from nirikshan.demo.scenarios import SCENARIOS

        for s in SCENARIOS.values():
            print(f"  {s.key:20s} {s.title}")
        return

    if args.cmd == "seed":
        print(json.dumps(_seed(), indent=2, default=str))
        return

    if args.cmd == "scenario":
        from nirikshan.ai.prompts import sync_prompts
        from nirikshan.demo.flow import drive_remediation
        from nirikshan.demo.scenarios import run_scenario
        from nirikshan.incidents.engine import get_by_ref
        from nirikshan.security.users import ensure_bootstrap_admin

        with session_scope() as db:
            sync_prompts(db)
            ensure_bootstrap_admin(db)
        with session_scope() as db:
            result = run_scenario(db, args.key, propose_fix=args.remediate)
            incident_ref = result.incident_ref
        out = {
            "scenario": result.scenario,
            "incident_ref": result.incident_ref,
            "anomalies": result.anomalies,
            "alerts": result.alerts,
            "root_cause": result.root_cause,
            "confidence": result.confidence,
            "top_hypothesis_category": result.top_hypothesis_category,
            "expected_category": result.expected_category,
            "category_match": result.category_match,
        }
        if args.remediate and incident_ref:
            with session_scope() as db:
                inc = get_by_ref(db, incident_ref)
                flow = drive_remediation(db, inc, scenario_key=args.key)
                out["remediation"] = {
                    "ref": flow.remediation_ref, "action": flow.action_name,
                    "verified": flow.verified, "incident_status": flow.incident_status,
                    "steps": flow.steps,
                }
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
