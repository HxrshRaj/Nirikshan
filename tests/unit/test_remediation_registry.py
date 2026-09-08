import pytest

from nirikshan.core.errors import ValidationFailure
from nirikshan.remediation.registry import (
    REGISTRY,
    get_action,
    resolve_service,
    runtime_state,
)
from tests.helpers import make_service

pytestmark = pytest.mark.unit


def test_registry_actions_have_complete_specs():
    for name, spec in REGISTRY.items():
        assert spec.name == name
        assert spec.parameters_schema.get("service", {}).get("required") is True
        assert spec.default_risk in ("LOW", "MEDIUM", "HIGH")
        assert callable(spec.apply)
        if spec.reversible:
            assert callable(spec.revert)


def test_get_action_rejects_unknown():
    with pytest.raises(ValidationFailure):
        get_action("format_c_drive")


def test_validate_params_rejects_unknown_and_missing():
    spec = get_action("scale_demo_service")
    with pytest.raises(ValidationFailure):
        spec.validate_params({})  # missing 'service'
    with pytest.raises(ValidationFailure):
        spec.validate_params({"service": "x", "danger": 1})  # unknown key
    spec.validate_params({"service": "x", "replicas_delta": 2})  # ok


def test_scale_apply_and_revert(db):
    svc = make_service(db, "pay")
    before = runtime_state(svc)
    get_action("scale_demo_service").apply(db, svc, {"service": "pay", "replicas_delta": 3, "connection_pool_delta": 10})
    after = runtime_state(svc)
    assert after["replicas"] == before["replicas"] + 3
    assert after["connection_pool"] == before["connection_pool"] + 10
    assert "traffic_overload" in (svc.attributes.get("suppressed_faults") or [])

    get_action("scale_demo_service").revert(db, svc, {"service": "pay", "replicas_delta": 3, "connection_pool_delta": 10})
    assert runtime_state(svc)["replicas"] == before["replicas"]


def test_feature_flag_apply_and_revert(db):
    svc = make_service(db, "pay")
    get_action("disable_demo_feature_flag").apply(db, svc, {"service": "pay", "flag": "require-postgresql"})
    assert runtime_state(svc)["feature_flags"]["require-postgresql"] is False
    get_action("disable_demo_feature_flag").revert(db, svc, {"service": "pay", "flag": "require-postgresql"})
    assert runtime_state(svc)["feature_flags"]["require-postgresql"] is True


def test_rollback_records_new_deployment(db):
    from nirikshan.core.clock import utcnow
    from nirikshan.core.ids import short_token
    from nirikshan.models import Deployment

    svc = make_service(db, "order-service")
    dep = Deployment(
        ref="DEP-" + short_token(6), environment_id=svc.environment_id, service_id=svc.id,
        service_name=svc.name, version="v2.0", previous_version="v1.9",
        started_at=utcnow(), status="SUCCEEDED", triggered_by="ci",
    )
    db.add(dep)
    db.flush()
    out = get_action("rollback_demo_deployment").apply(
        db, svc, {"service": "order-service", "deployment_ref": dep.ref, "to_version": "previous"}
    )
    assert out["now_serving"] == "v1.9"
    db.refresh(dep)
    assert dep.status == "ROLLED_BACK"
    assert db.query(Deployment).filter_by(triggered_by="nirikshan-remediation").count() == 1


def test_resolve_service_requires_service_param(db):
    with pytest.raises(ValidationFailure):
        resolve_service(db, {})
