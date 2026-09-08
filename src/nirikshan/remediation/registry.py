"""Registry of explicitly-allowed remediation actions (spec 30, 32).

The AI may only *request* one of these by name with typed parameters. There is
no path from model output to a shell command. Each action operates on the demo
environment's runtime state, which is stored on ``Service.attributes`` so it is
observable and shared across the API and worker processes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from nirikshan.catalog.service import find_service
from nirikshan.core.clock import utcnow
from nirikshan.core.errors import ValidationFailure
from nirikshan.core.ids import short_token
from nirikshan.domain.enums import DeploymentStatus, Role
from nirikshan.models import Deployment, Service

# Default runtime state a demo service is assumed to have.
DEFAULT_RUNTIME = {"replicas": 3, "connection_pool": 50, "feature_flags": {}, "cache_generation": 1}


def runtime_state(service: Service) -> dict:
    rt = dict(DEFAULT_RUNTIME)
    rt.update((service.attributes or {}).get("runtime", {}))
    return rt


def _write_runtime(db: Session, service: Service, rt: dict, *, suppress_fault: str | None = None) -> None:
    attrs = dict(service.attributes or {})
    attrs["runtime"] = rt
    if suppress_fault:
        suppressed = set(attrs.get("suppressed_faults", []))
        suppressed.add(suppress_fault)
        attrs["suppressed_faults"] = sorted(suppressed)
    attrs["runtime_updated_at"] = utcnow().isoformat()
    service.attributes = attrs
    db.add(service)
    db.flush()


@dataclass
class ActionSpec:
    name: str
    description: str
    parameters_schema: dict
    default_risk: str
    reversible: bool
    requires_role: Role
    apply: Callable[..., dict]
    revert: Callable[..., dict] | None = None
    fault_tags: list[str] = field(default_factory=list)

    def validate_params(self, params: dict) -> None:
        for key, spec in self.parameters_schema.items():
            required = spec.get("required", False)
            if required and key not in params:
                raise ValidationFailure(f"{self.name}: missing required parameter {key!r}")
        unknown = set(params) - set(self.parameters_schema)
        if unknown:
            raise ValidationFailure(f"{self.name}: unknown parameters {sorted(unknown)}")


# --------------------------------------------------------------------------- #
# Action implementations (operate on demo runtime state only)
# --------------------------------------------------------------------------- #
def _apply_rollback(db: Session, service: Service, params: dict) -> dict:
    to_version = params.get("to_version") or "previous"
    dep_ref = params.get("deployment_ref")
    before_version = None
    target = None
    if dep_ref:
        target = db.query(Deployment).filter(Deployment.ref == dep_ref).one_or_none()
    if target is None:
        target = (
            db.query(Deployment)
            .filter(Deployment.service_id == service.id)
            .order_by(Deployment.started_at.desc())
            .first()
        )
    if target is not None:
        before_version = target.version
        target.status = DeploymentStatus.ROLLED_BACK.value
        db.add(target)
        if to_version in ("previous", None) and target.previous_version:
            to_version = target.previous_version
    now = utcnow()
    rollfwd = Deployment(
        ref="DEP-" + short_token(6),
        environment_id=service.environment_id,
        service_id=service.id,
        service_name=service.name,
        version=to_version,
        previous_version=before_version,
        change_summary=f"Automated rollback via Nirikshan remediation (from {before_version})",
        started_at=now,
        completed_at=now,
        status=DeploymentStatus.SUCCEEDED.value,
        triggered_by="nirikshan-remediation",
    )
    db.add(rollfwd)
    rt = runtime_state(service)
    rt["version"] = to_version
    _write_runtime(db, service, rt, suppress_fault="deployment_regression")
    _write_runtime(db, service, rt, suppress_fault="database_saturation")
    db.flush()
    return {"rolled_back_from": before_version, "now_serving": to_version, "new_deployment": rollfwd.ref}


def _revert_rollback(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    rt["version"] = params.get("from_version") or rt.get("version")
    attrs = dict(service.attributes or {})
    attrs["suppressed_faults"] = [
        f for f in attrs.get("suppressed_faults", []) if f not in ("deployment_regression", "database_saturation")
    ]
    attrs["runtime"] = rt
    service.attributes = attrs
    db.add(service)
    db.flush()
    return {"restored_version": rt["version"]}


def _apply_scale(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    before = {"replicas": rt["replicas"], "connection_pool": rt["connection_pool"]}
    rt["replicas"] = max(1, rt["replicas"] + int(params.get("replicas_delta", 1)))
    rt["connection_pool"] = max(5, rt["connection_pool"] + int(params.get("connection_pool_delta", 0)))
    _write_runtime(db, service, rt, suppress_fault="traffic_overload")
    _write_runtime(db, service, rt, suppress_fault="database_saturation")
    return {"before": before, "after": {"replicas": rt["replicas"], "connection_pool": rt["connection_pool"]}}


def _revert_scale(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    rt["replicas"] = max(1, rt["replicas"] - int(params.get("replicas_delta", 1)))
    rt["connection_pool"] = max(5, rt["connection_pool"] - int(params.get("connection_pool_delta", 0)))
    attrs = dict(service.attributes or {})
    attrs["runtime"] = rt
    attrs["suppressed_faults"] = [
        f for f in attrs.get("suppressed_faults", []) if f not in ("traffic_overload", "database_saturation")
    ]
    service.attributes = attrs
    db.add(service)
    db.flush()
    return {"after": {"replicas": rt["replicas"], "connection_pool": rt["connection_pool"]}}


def _apply_restart(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    rt["last_restart"] = utcnow().isoformat()
    _write_runtime(db, service, rt, suppress_fault="resource_saturation")
    for inst in service.instances:
        inst.last_seen_at = utcnow()
        db.add(inst)
    db.flush()
    return {"restarted": service.name, "strategy": params.get("strategy", "rolling"), "instances": len(service.instances)}


def _apply_flag(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    flags = dict(rt.get("feature_flags", {}))
    flag = params["flag"]
    before = flags.get(flag)
    flags[flag] = False
    rt["feature_flags"] = flags
    _write_runtime(db, service, rt, suppress_fault="upstream_dependency_failure")
    _write_runtime(db, service, rt, suppress_fault="deployment_regression")
    return {"flag": flag, "before": before, "after": False}


def _revert_flag(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    flags = dict(rt.get("feature_flags", {}))
    flags[params["flag"]] = True
    rt["feature_flags"] = flags
    attrs = dict(service.attributes or {})
    attrs["runtime"] = rt
    attrs["suppressed_faults"] = [
        f for f in attrs.get("suppressed_faults", []) if f not in ("upstream_dependency_failure", "deployment_regression")
    ]
    service.attributes = attrs
    db.add(service)
    db.flush()
    return {"flag": params["flag"], "after": True}


def _apply_clear_cache(db: Session, service: Service, params: dict) -> dict:
    rt = runtime_state(service)
    rt["cache_generation"] = int(rt.get("cache_generation", 1)) + 1
    _write_runtime(db, service, rt)
    return {"cache_generation": rt["cache_generation"]}


REGISTRY: dict[str, ActionSpec] = {
    "rollback_demo_deployment": ActionSpec(
        name="rollback_demo_deployment",
        description="Roll a service back to a previous deployment version (demo environment).",
        parameters_schema={
            "service": {"type": "str", "required": True},
            "to_version": {"type": "str"},
            "from_version": {"type": "str"},
            "deployment_ref": {"type": "str"},
        },
        default_risk="MEDIUM",
        reversible=True,
        requires_role=Role.INCIDENT_COMMANDER,
        apply=_apply_rollback,
        revert=_revert_rollback,
        fault_tags=["deployment_regression", "database_saturation"],
    ),
    "scale_demo_service": ActionSpec(
        name="scale_demo_service",
        description="Adjust replica count / connection pool for a service (demo environment).",
        parameters_schema={
            "service": {"type": "str", "required": True},
            "replicas_delta": {"type": "int"},
            "connection_pool_delta": {"type": "int"},
        },
        default_risk="LOW",
        reversible=True,
        requires_role=Role.ENGINEER,
        apply=_apply_scale,
        revert=_revert_scale,
        fault_tags=["traffic_overload", "database_saturation"],
    ),
    "restart_demo_service": ActionSpec(
        name="restart_demo_service",
        description="Rolling restart of a service's instances (demo environment).",
        parameters_schema={"service": {"type": "str", "required": True}, "strategy": {"type": "str"}},
        default_risk="MEDIUM",
        reversible=False,
        requires_role=Role.ENGINEER,
        apply=_apply_restart,
        revert=None,
        fault_tags=["resource_saturation"],
    ),
    "disable_demo_feature_flag": ActionSpec(
        name="disable_demo_feature_flag",
        description="Disable a feature flag to enter degraded mode (demo environment).",
        parameters_schema={
            "service": {"type": "str", "required": True},
            "flag": {"type": "str", "required": True},
            "reason": {"type": "str"},
        },
        default_risk="LOW",
        reversible=True,
        requires_role=Role.ENGINEER,
        apply=_apply_flag,
        revert=_revert_flag,
        fault_tags=["upstream_dependency_failure", "deployment_regression"],
    ),
    "clear_demo_cache": ActionSpec(
        name="clear_demo_cache",
        description="Bump the cache generation to invalidate a service's cache (demo environment).",
        parameters_schema={"service": {"type": "str", "required": True}},
        default_risk="LOW",
        reversible=False,
        requires_role=Role.ENGINEER,
        apply=_apply_clear_cache,
        revert=None,
        fault_tags=[],
    ),
}


def get_action(name: str) -> ActionSpec:
    spec = REGISTRY.get(name)
    if spec is None:
        raise ValidationFailure(f"action {name!r} is not in the remediation allowlist")
    return spec


def resolve_service(db: Session, params: dict, *, environment: str = "production") -> Service:
    name = params.get("service")
    if not name:
        raise ValidationFailure("action parameters must include 'service'")
    svc = find_service(db, str(name).lower(), environment=environment)
    if svc is None:
        raise ValidationFailure(f"unknown service {name!r}")
    return svc
