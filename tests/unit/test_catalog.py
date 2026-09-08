import pytest

from nirikshan.catalog.service import (
    add_dependency,
    create_service,
    find_service,
    get_or_create_environment,
    get_or_create_service,
    get_service,
    list_services,
)
from nirikshan.core.errors import ConflictError, NotFoundError
from nirikshan.schemas.catalog import DependencyIn, ServiceIn

pytestmark = pytest.mark.unit


def test_get_or_create_is_idempotent(db):
    a = get_or_create_service(db, "svc-x", environment="production")
    b = get_or_create_service(db, "svc-x", environment="production")
    assert a.id == b.id
    assert len(list_services(db, environment="production")) == 1


def test_create_service_rejects_duplicate(db):
    payload = ServiceIn(name="dup", environment="production")
    create_service(db, payload)
    with pytest.raises(ConflictError):
        create_service(db, payload)


def test_get_service_not_found(db):
    get_or_create_environment(db, "production")
    with pytest.raises(NotFoundError):
        get_service(db, "nope", environment="production")
    assert find_service(db, "nope") is None


def test_add_dependency_rejects_self_and_dedups(db):
    get_or_create_service(db, "a", environment="production")
    get_or_create_service(db, "b", environment="production")
    with pytest.raises(ConflictError):
        add_dependency(db, DependencyIn(upstream="a", downstream="a", environment="production"))
    e1 = add_dependency(db, DependencyIn(upstream="a", downstream="b", environment="production"))
    e2 = add_dependency(db, DependencyIn(upstream="a", downstream="b", environment="production"))
    assert e1.id == e2.id


def test_unknown_service_auto_registered_at_tier_3(db):
    svc = get_or_create_service(db, "auto", environment="production", tier=3)
    assert svc.tier == 3
