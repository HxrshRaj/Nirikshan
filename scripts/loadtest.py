#!/usr/bin/env python
"""Telemetry ingestion load test.

Drives batched metric ingestion against a running API and reports events/sec and
per-batch latency percentiles. Numbers are host-dependent — record your
environment when you quote them; do not treat any output here as a benchmark.

Usage:
    python scripts/loadtest.py --url http://localhost:8000 \
        --email admin@nirikshan.dev --password admin12345 \
        --batches 200 --batch-size 500 --concurrency 8
"""

from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

SERVICES = ["api-gateway", "order-service", "payment-service", "inventory-service"]
METRICS = ["request_latency_ms", "request_count", "error_rate", "cpu_usage"]


def _batch(n: int) -> dict:
    now = time.time()
    return {
        "metrics": [
            {
                "service": SERVICES[i % len(SERVICES)],
                "metric_name": METRICS[i % len(METRICS)],
                "value": 100.0 + (i % 50),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + "Z",
            }
            for i in range(n)
        ]
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--email", default="admin@nirikshan.dev")
    ap.add_argument("--password", default="admin12345")
    ap.add_argument("--batches", type=int, default=100)
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    with httpx.Client(base_url=args.url, timeout=30) as c:
        tok = c.post("/api/auth/login", json={"email": args.email, "password": args.password}).json()[
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {tok}"}
        payload = _batch(args.batch_size)

        latencies: list[float] = []
        accepted = 0
        errors = 0

        def one(_i: int):
            t0 = time.perf_counter()
            r = c.post("/api/telemetry/metrics", json=payload, headers=headers)
            dt = (time.perf_counter() - t0) * 1000
            return dt, r.status_code, r.json() if r.status_code == 200 else None

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for dt, code, body in pool.map(one, range(args.batches)):
                latencies.append(dt)
                if code == 200 and body:
                    accepted += body.get("accepted", 0)
                else:
                    errors += 1
        wall = time.perf_counter() - start

    total_events = accepted
    latencies.sort()
    def p(q):
        return latencies[min(int(q * (len(latencies) - 1)), len(latencies) - 1)]
    print("host / conditions : record these yourself (CPU, cores, DB backend, network)")
    print(f"batches           : {args.batches} x {args.batch_size} metrics, concurrency {args.concurrency}")
    print(f"wall time         : {wall:.2f}s")
    print(f"accepted events   : {total_events}  ({errors} failed batches)")
    print(f"throughput        : {total_events / wall:,.0f} events/sec")
    print(f"batch latency ms  : p50={p(0.5):.1f}  p95={p(0.95):.1f}  p99={p(0.99):.1f}  max={latencies[-1]:.1f}")
    print(f"batch latency mean: {statistics.mean(latencies):.1f} ms")


if __name__ == "__main__":
    main()
