"""Pure unit coverage for grpc_service/server.py's snapshot -> proto mapping.

No server, no client, no network - just proves the wire message faithfully
mirrors nirikshan.telemetry.aggregate.ServiceHealthSnapshot field-for-field,
including the "None means no telemetry yet" -> unset optional distinction.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grpc_service.generated import service_health_pb2 as pb2
from grpc_service.server import snapshot_to_proto

from nirikshan.domain.enums import ServiceHealth
from nirikshan.telemetry.aggregate import ServiceHealthSnapshot

pytestmark = pytest.mark.unit


def _snapshot(**overrides) -> ServiceHealthSnapshot:
    base = dict(
        service="payment-service",
        service_id="svc-123",
        tier=1,
        health=ServiceHealth.DEGRADED,
        window_seconds=600,
        latency_p95_ms=842.0,
        latency_avg_ms=310.5,
        error_rate=0.0421,
        request_rate_per_min=118.0,
        log_error_count=7,
        cpu_usage=0.61,
        memory_usage=0.72,
        db_connections=88.0,
        queue_depth=None,
        reasons=["p95 latency 842ms > SLO 300ms", "error rate 4.2% > SLO 2.0%"],
    )
    base.update(overrides)
    return ServiceHealthSnapshot(**base)


def test_maps_every_field_faithfully():
    snap = _snapshot()
    update = snapshot_to_proto(snap)

    assert update.service_name == snap.service
    assert update.tier == snap.tier
    assert update.status == pb2.DEGRADED
    assert update.window_seconds == snap.window_seconds
    assert update.latency_p95_ms == pytest.approx(snap.latency_p95_ms)
    assert update.latency_avg_ms == pytest.approx(snap.latency_avg_ms)
    assert update.error_rate == pytest.approx(snap.error_rate)
    assert update.request_rate_per_min == pytest.approx(snap.request_rate_per_min)
    assert update.log_error_count == snap.log_error_count
    assert update.cpu_usage == pytest.approx(snap.cpu_usage)
    assert update.memory_usage == pytest.approx(snap.memory_usage)
    assert update.db_connections == pytest.approx(snap.db_connections)
    assert list(update.reasons) == snap.reasons
    assert update.computed_at_unix_ms > 0


def test_none_fields_stay_unset_not_zero():
    snap = _snapshot(latency_p95_ms=None, error_rate=None, queue_depth=None)
    update = snapshot_to_proto(snap)

    assert not update.HasField("latency_p95_ms")
    assert not update.HasField("error_rate")
    assert not update.HasField("queue_depth")
    # a real zero elsewhere must still read as present, not accidentally cleared
    snap_zero = _snapshot(error_rate=0.0)
    assert snapshot_to_proto(snap_zero).HasField("error_rate")
    assert snapshot_to_proto(snap_zero).error_rate == 0.0


@pytest.mark.parametrize(
    "health, expected",
    [
        (ServiceHealth.HEALTHY, pb2.HEALTHY),
        (ServiceHealth.DEGRADED, pb2.DEGRADED),
        (ServiceHealth.UNHEALTHY, pb2.UNHEALTHY),
        (ServiceHealth.UNKNOWN, pb2.UNKNOWN),
    ],
)
def test_every_health_status_maps(health, expected):
    update = snapshot_to_proto(_snapshot(health=health))
    assert update.status == expected
