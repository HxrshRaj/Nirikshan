"""Remediation policy engine (spec 31, 38, 101).

    AI proposal -> policy validation -> permission check -> risk assessment ->
    human approval (if required) -> execution

``evaluate`` returns a decision plus a list of findings. It never executes
anything; it only says whether execution is allowed now, needs approval, or is
denied outright.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from nirikshan.core.config import get_settings
from nirikshan.domain.enums import IncidentStatus, RemediationMode, Role
from nirikshan.models import Incident
from nirikshan.remediation.registry import ActionSpec, get_action, resolve_service

_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


@dataclass
class PolicyFinding:
    level: str  # info | warn | block
    code: str
    message: str


@dataclass
class PolicyDecision:
    allowed_now: bool
    requires_approval: bool
    min_role: Role
    effective_mode: RemediationMode
    findings: list[PolicyFinding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.level == "block" for f in self.findings)

    def as_list(self) -> list[dict]:
        return [f.__dict__ for f in self.findings]


def evaluate(
    db: Session,
    *,
    incident: Incident,
    action_name: str,
    parameters: dict,
    risk: str,
    rca_confidence: float | None,
    actor_role: Role | None = None,
    mode_override: str | None = None,
) -> PolicyDecision:
    settings = get_settings()
    mode = RemediationMode(mode_override or settings.remediation_mode)
    findings: list[PolicyFinding] = []

    # 1. allowlist + parameter schema
    try:
        spec: ActionSpec = get_action(action_name)
        spec.validate_params(parameters)
    except Exception as exc:
        findings.append(PolicyFinding("block", "invalid_action", str(exc)))
        return PolicyDecision(False, True, Role.ADMIN, mode, findings)

    # 2. service resolves
    try:
        resolve_service(db, parameters)
    except Exception as exc:
        findings.append(PolicyFinding("block", "unknown_service", str(exc)))
        return PolicyDecision(False, True, Role.ADMIN, mode, findings)

    # 3. incident state
    if IncidentStatus(incident.status) in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        findings.append(
            PolicyFinding("block", "incident_not_open",
                          f"incident {incident.ref} is {incident.status}; refusing remediation")
        )

    # 4. risk vs confidence
    risk = risk.upper()
    if risk not in _RISK_RANK:
        risk = "MEDIUM"
    if rca_confidence is not None and rca_confidence < 0.5 and _RISK_RANK[risk] >= 1:
        findings.append(
            PolicyFinding("warn", "low_confidence",
                          f"RCA confidence {rca_confidence:.2f} is low for a {risk}-risk action")
        )

    # 5. effective approval requirement
    requires_approval = True
    if mode == RemediationMode.OBSERVE:
        findings.append(PolicyFinding("block", "observe_mode", "remediation mode is OBSERVE; no actions may run"))
    elif mode == RemediationMode.RECOMMEND:
        findings.append(PolicyFinding("info", "recommend_mode", "mode RECOMMEND: action is advisory only"))
    elif mode == RemediationMode.APPROVAL_REQUIRED:
        requires_approval = True
    elif mode == RemediationMode.AUTONOMOUS:
        autonomous_ok = (
            _RISK_RANK[risk] == 0
            and spec.reversible
            and (rca_confidence or 0) >= 0.8
        )
        requires_approval = not autonomous_ok
        if not autonomous_ok:
            findings.append(
                PolicyFinding("info", "autonomous_gate",
                              "action does not meet the autonomous bar (LOW risk + reversible + confidence>=0.8); "
                              "human approval still required")
            )

    if risk == "HIGH":
        requires_approval = True
        findings.append(PolicyFinding("warn", "high_risk", "HIGH-risk action always requires explicit human approval"))

    min_role = Role.INCIDENT_COMMANDER if (requires_approval or _RISK_RANK[risk] >= 1) else spec.requires_role
    if _RISK_RANK[risk] >= 1 and spec.requires_role.rank > min_role.rank:
        min_role = spec.requires_role

    blocked = any(f.level == "block" for f in findings)
    allowed_now = (not blocked) and (not requires_approval)
    if not blocked and requires_approval:
        findings.append(
            PolicyFinding("info", "approval_required",
                          f"requires approval from {min_role.value} or higher")
        )
    return PolicyDecision(
        allowed_now=allowed_now,
        requires_approval=requires_approval and not blocked,
        min_role=min_role,
        effective_mode=mode,
        findings=findings,
    )
