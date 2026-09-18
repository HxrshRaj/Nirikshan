#!/usr/bin/env python
"""Nirikshan gRPC server: real-time service-health streaming.

Runs alongside the existing FastAPI REST API (different port), reading from
the exact same database via the exact same
``nirikshan.telemetry.aggregate.compute_service_health`` computation the REST
API, the dashboard, and the alert engine already use. This process never
touches telemetry directly and never invents data - it is a thin transport
(gRPC server-streaming) over data Nirikshan already computes.

Run:
    python grpc_service/server.py
    NIRIKSHAN_GRPC_PORT=50051 python grpc_service/server.py
"""

from __future__ import annotations

import signal
import sys
import time
from concurrent import futures
from datetime import UTC, datetime
from pathlib import Path

import grpc

# Run directly as `python grpc_service/server.py` (documented usage, matches
# evaluation/run_eval.py's style elsewhere in this repo): Python then puts this
# file's own directory - not the repo root - on sys.path[0], so the
# package-qualified `grpc_service.generated` import below would otherwise fail.
# `nirikshan.*` doesn't need this: it's pip-installed (`pip install -e .`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from grpc_service.generated import service_health_pb2 as pb2  # noqa: E402
from grpc_service.generated import service_health_pb2_grpc as pb2_grpc  # noqa: E402
from nirikshan.catalog.service import find_service  # noqa: E402
from nirikshan.core.clock import utcnow  # noqa: E402
from nirikshan.core.config import get_settings  # noqa: E402
from nirikshan.core.db import init_engine, session_scope  # noqa: E402
from nirikshan.core.logging import configure_logging, get_logger  # noqa: E402
from nirikshan.domain.enums import ServiceHealth  # noqa: E402
from nirikshan.telemetry.aggregate import ServiceHealthSnapshot, compute_service_health  # noqa: E402

log = get_logger("grpc.server")

_STATUS_TO_PROTO: dict[ServiceHealth, int] = {
    ServiceHealth.HEALTHY: pb2.HEALTHY,
    ServiceHealth.DEGRADED: pb2.DEGRADED,
    ServiceHealth.UNHEALTHY: pb2.UNHEALTHY,
    ServiceHealth.UNKNOWN: pb2.UNKNOWN,
}


def snapshot_to_proto(snap: ServiceHealthSnapshot) -> pb2.ServiceHealthUpdate:
    """Map the real, already-computed dataclass to the wire message field-for-field.

    Pure function (no I/O) so it's covered by a plain unit test without needing a
    running server, a database, or a client.
    """
    update = pb2.ServiceHealthUpdate(
        service_name=snap.service,
        tier=snap.tier,
        status=_STATUS_TO_PROTO.get(snap.health, pb2.HEALTH_STATUS_UNSPECIFIED),
        window_seconds=snap.window_seconds,
        log_error_count=snap.log_error_count,
        reasons=list(snap.reasons),
        computed_at_unix_ms=int(datetime.now(UTC).timestamp() * 1000),
    )
    # `optional double` fields: only set when the source has a real value, so the
    # client can tell "no telemetry yet" (unset) apart from a genuine 0.0.
    if snap.latency_p95_ms is not None:
        update.latency_p95_ms = snap.latency_p95_ms
    if snap.latency_avg_ms is not None:
        update.latency_avg_ms = snap.latency_avg_ms
    if snap.error_rate is not None:
        update.error_rate = snap.error_rate
    if snap.request_rate_per_min is not None:
        update.request_rate_per_min = snap.request_rate_per_min
    if snap.cpu_usage is not None:
        update.cpu_usage = snap.cpu_usage
    if snap.memory_usage is not None:
        update.memory_usage = snap.memory_usage
    if snap.db_connections is not None:
        update.db_connections = snap.db_connections
    if snap.queue_depth is not None:
        update.queue_depth = snap.queue_depth
    return update


def _resolve_window_seconds(request: pb2.ServiceHealthRequest) -> int:
    return request.window_seconds or get_settings().grpc_default_window_seconds


def _resolve_poll_interval(request: pb2.ServiceHealthRequest) -> int:
    return request.poll_interval_seconds or get_settings().grpc_default_poll_interval_seconds


def _compute(request: pb2.ServiceHealthRequest) -> ServiceHealthSnapshot | None:
    """One real read: open a session, resolve the service, compute its health.

    A short-lived session per poll tick (rather than one held for the whole
    stream) matches how the rest of the codebase uses ``session_scope`` and
    avoids holding a DB connection open for the lifetime of a long streaming
    call.
    """
    environment = request.environment or "production"
    with session_scope() as db:
        svc = find_service(db, request.service_name.strip().lower(), environment=environment)
        if svc is None:
            return None
        return compute_service_health(db, svc, window_seconds=_resolve_window_seconds(request))


class ServiceHealthStreamServicer(pb2_grpc.ServiceHealthStreamServicer):
    def GetServiceHealthSnapshot(self, request, context):  # grpc-generated method name (PascalCase)
        snap = _compute(request)
        if snap is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"unknown service: {request.service_name!r}")
        return snapshot_to_proto(snap)

    def StreamServiceHealth(self, request, context):  # grpc-generated method name (PascalCase)
        service_name = request.service_name.strip().lower()
        poll_interval = _resolve_poll_interval(request)
        log.info("grpc.stream.opened", service=service_name, poll_interval_s=poll_interval)

        last_emitted: pb2.ServiceHealthUpdate | None = None
        emitted_count = 0
        try:
            while context.is_active():
                snap = _compute(request)
                if snap is None:
                    context.abort(
                        grpc.StatusCode.NOT_FOUND, f"unknown service: {request.service_name!r}"
                    )
                    return

                update = snapshot_to_proto(snap)
                # Emit on the first tick, and again whenever the real computed values
                # actually changed - "as they change", not a fixed-interval replay.
                # (computed_at_unix_ms always differs, so compare everything else.)
                changed = last_emitted is None or not _content_equal(update, last_emitted)
                if changed:
                    emitted_count += 1
                    yield update
                    last_emitted = update

                time.sleep(poll_interval)
        except grpc.RpcError:
            pass
        finally:
            log.info(
                "grpc.stream.closed", service=service_name, updates_sent=emitted_count
            )


def _content_equal(a: pb2.ServiceHealthUpdate, b: pb2.ServiceHealthUpdate) -> bool:
    """Equality ignoring the always-different computed_at_unix_ms timestamp."""
    fa, fb = pb2.ServiceHealthUpdate(), pb2.ServiceHealthUpdate()
    fa.CopyFrom(a)
    fb.CopyFrom(b)
    fa.ClearField("computed_at_unix_ms")
    fb.ClearField("computed_at_unix_ms")
    return fa == fb


def serve() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    pb2_grpc.add_ServiceHealthStreamServicer_to_server(ServiceHealthStreamServicer(), server)
    bind = f"[::]:{settings.grpc_port}"
    server.add_insecure_port(bind)
    server.start()
    log.info(
        "grpc.started",
        bind=bind,
        env=settings.env,
        default_window_s=settings.grpc_default_window_seconds,
        default_poll_interval_s=settings.grpc_default_poll_interval_seconds,
        started_at=utcnow().isoformat(),
    )

    def _handle_signal(signum, _frame):
        log.info("grpc.stopping", signal=signum)
        server.stop(grace=5)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    server.wait_for_termination()
    log.info("grpc.stopped")


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
