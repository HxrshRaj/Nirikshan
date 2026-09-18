#!/usr/bin/env python
"""Real gRPC client for the Nirikshan ServiceHealthStream service.

Connects to a running grpc_service/server.py, calls the unary snapshot RPC
once, then subscribes to the streaming RPC and prints every update as it
arrives - proving the stream is live (changing values, changing timestamps),
not a static reply.

Usage:
    python grpc_service/client.py payment-service
    python grpc_service/client.py payment-service --host localhost --port 50051
    python grpc_service/client.py payment-service --max-updates 5   # exit after N updates (scripted verification)
    python grpc_service/client.py payment-service --poll-interval 1 --window 300
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import grpc

# See grpc_service/server.py for why this is needed when run directly as
# `python grpc_service/client.py` rather than `python -m grpc_service.client`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from grpc_service.generated import service_health_pb2 as pb2  # noqa: E402
from grpc_service.generated import service_health_pb2_grpc as pb2_grpc  # noqa: E402

_STATUS_NAME = {v: k for k, v in pb2.HealthStatus.items()}


def _fmt(update: pb2.ServiceHealthUpdate) -> str:
    when = datetime.fromtimestamp(update.computed_at_unix_ms / 1000, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"[{when}] {update.service_name} tier={update.tier} status={pb2.HealthStatus.Name(update.status)}"]
    if update.HasField("error_rate"):
        parts.append(f"error_rate={update.error_rate:.4f}")
    if update.HasField("latency_p95_ms"):
        parts.append(f"p95={update.latency_p95_ms:.1f}ms")
    if update.HasField("latency_avg_ms"):
        parts.append(f"avg={update.latency_avg_ms:.1f}ms")
    if update.HasField("request_rate_per_min"):
        parts.append(f"req/min={update.request_rate_per_min:.1f}")
    parts.append(f"log_errors={update.log_error_count}")
    if update.reasons:
        parts.append("reasons=" + "; ".join(update.reasons))
    return "  ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("service_name", help="e.g. payment-service (must exist in Nirikshan's catalogue)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--environment", default="production")
    parser.add_argument("--window", type=int, default=0, help="seconds; 0 = server default (600)")
    parser.add_argument("--poll-interval", type=int, default=0, help="seconds; 0 = server default (2)")
    parser.add_argument(
        "--max-updates", type=int, default=0,
        help="exit after N streamed updates (0 = run until Ctrl+C); useful for automated verification",
    )
    args = parser.parse_args()

    target = f"{args.host}:{args.port}"
    request = pb2.ServiceHealthRequest(
        service_name=args.service_name,
        environment=args.environment,
        window_seconds=args.window,
        poll_interval_seconds=args.poll_interval,
    )

    print(f"connecting to {target} ...")
    with grpc.insecure_channel(target) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
        except grpc.FutureTimeoutError:
            print(f"could not reach the gRPC server at {target} - is grpc_service/server.py running?",
                  file=sys.stderr)
            return 1

        stub = pb2_grpc.ServiceHealthStreamStub(channel)

        print("\n--- unary: one-off snapshot (GetServiceHealthSnapshot) ---")
        try:
            snapshot = stub.GetServiceHealthSnapshot(request, timeout=10)
            print(_fmt(snapshot))
        except grpc.RpcError as e:
            print(f"GetServiceHealthSnapshot failed: {e.code()} - {e.details()}", file=sys.stderr)
            return 1

        print(f"\n--- streaming: live updates (StreamServiceHealth) - service={args.service_name} ---")
        print("(Ctrl+C to stop" + (f", or after {args.max_updates} updates" if args.max_updates else "") + ")\n")

        count = 0
        try:
            for update in stub.StreamServiceHealth(request):
                count += 1
                print(f"#{count}  {_fmt(update)}")
                if args.max_updates and count >= args.max_updates:
                    print(f"\nreceived {count} update(s); stopping (--max-updates reached).")
                    break
        except grpc.RpcError as e:
            print(f"\nstream ended: {e.code()} - {e.details()}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(f"\nstopped by user after {count} update(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
