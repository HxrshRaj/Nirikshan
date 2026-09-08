from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, rate_limit, require_role
from nirikshan.core.errors import NotFoundError
from nirikshan.demo.scenarios import SCENARIOS, run_scenario
from nirikshan.domain.enums import Role
from nirikshan.incidents.engine import get_by_ref
from nirikshan.models import User
from nirikshan.security import audit

router = APIRouter(tags=["demo"], prefix="/demo")


class ScenarioRunIn(BaseModel):
    scenario: str
    investigate: bool = True
    propose_remediation: bool = False


class DriveRemediationIn(BaseModel):
    incident_ref: str
    scenario: str


@router.get("/scenarios")
def list_scenarios(_u: User = Depends(current_user)) -> list[dict]:
    return [
        {"key": s.key, "title": s.title, "description": s.description,
         "expected_category": s.expected_category, "expected_service": s.expected_service}
        for s in SCENARIOS.values()
    ]


@router.post("/seed")
def seed(
    db: Session = Depends(get_db), user: User = Depends(require_role(Role.ADMIN))
) -> dict:
    from nirikshan.demo.generator import generate
    from nirikshan.demo.topology import ensure_topology
    from nirikshan.security.users import seed_demo_users

    seed_demo_users(db)
    services = ensure_topology(db)
    db.flush()
    info = generate(db, scenario=None)
    audit.record(db, actor=user.email, actor_role=user.role, action="demo.seed", resource_type="demo")
    return {"services": len(services), "telemetry": info,
            "demo_users": "one per role, password '<role>12345'"}


@router.post("/run-scenario", dependencies=[Depends(rate_limit("default"))])
def run(
    payload: ScenarioRunIn, db: Session = Depends(get_db), user: User = Depends(require_role(Role.ADMIN))
) -> dict:
    if payload.scenario not in SCENARIOS:
        raise NotFoundError(f"unknown scenario {payload.scenario!r}")
    result = run_scenario(
        db, payload.scenario, investigate_incident=payload.investigate,
        propose_fix=payload.propose_remediation,
    )
    audit.record(db, actor=user.email, actor_role=user.role, action="demo.run_scenario",
                 resource_type="demo", resource_id=payload.scenario,
                 after={"incident": result.incident_ref})
    return {
        "scenario": result.scenario,
        "seeded": result.seeded,
        "anomalies": result.anomalies,
        "alerts": result.alerts,
        "incident_ref": result.incident_ref,
        "investigation_run_id": result.investigation_run_id,
        "root_cause": result.root_cause,
        "confidence": result.confidence,
        "top_hypothesis_category": result.top_hypothesis_category,
        "expected_category": result.expected_category,
        "category_match": result.category_match,
        "remediation_ref": result.remediation_ref,
    }


@router.post("/drive-remediation", dependencies=[Depends(rate_limit("remediation"))])
def drive_remediation(
    payload: DriveRemediationIn, db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.INCIDENT_COMMANDER)),
) -> dict:
    from nirikshan.demo.flow import drive_remediation as _drive

    inc = get_by_ref(db, payload.incident_ref)
    if inc is None:
        raise NotFoundError(f"incident {payload.incident_ref} not found")
    res = _drive(db, inc, scenario_key=payload.scenario, approver=user.email, approver_role=Role(user.role))
    audit.record(db, actor=user.email, actor_role=user.role, action="demo.drive_remediation",
                 resource_type="incident", resource_id=inc.ref,
                 after={"remediation_ref": res.remediation_ref, "verified": res.verified})
    return res.__dict__
