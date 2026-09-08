# Load Testing

`scripts/loadtest.py` drives batched metric ingestion (`POST /api/telemetry/metrics`)
against a running API and reports throughput + per-batch latency percentiles.

```bash
python scripts/loadtest.py --url http://localhost:8000 \
  --email admin@nirikshan.dev --password admin12345 \
  --batches 200 --batch-size 500 --concurrency 8
```

## Numbers are host-dependent — always record conditions

The run below is illustrative only. It is **not** a benchmark and must not be
quoted without its environment.

### Recorded run (2026-09-08)

| | |
|---|---|
| Host | Windows 11, 13th Gen Intel Core i5-1335U (12 logical cores), 15.7 GB RAM (laptop, on battery/dev machine) |
| Stack | `docker compose` — `api` (uvicorn, 1 worker), `postgres:16-alpine`, `redis:7-alpine`, `worker`, all on the same host under Docker Desktop (WSL2, 12 CPU / ~7.6 GB to the VM) |
| Client | same host, `httpx` + `ThreadPoolExecutor`, concurrency 8 |
| Payload | 200 batches × 500 metrics = **100,000 events**, 0 failed batches |

| Metric | Value |
|---|---|
| Wall time | 47.9 s |
| Throughput | **~2,090 events/sec** |
| Batch latency p50 | 1,647 ms |
| Batch latency p95 | 2,471 ms |
| Batch latency p99 | 7,134 ms |
| Batch latency mean | 1,897 ms |

Container CPU during the run: `postgres` ~18 %, `api` <1 %, `redis` <1 %.

### Reading these numbers

- Throughput is bounded by the **write path**, not the API: `postgres` was the
  only container doing real work. The ingestion service resolves
  `(environment, service)` per batch (cached) then does an ORM `add_all` +
  `flush` of the whole batch. With 8 concurrent 500-row flushes into the same
  unpartitioned tables on a single-worker `api` process on a laptop, contention
  dominates — hence the wide p50→p99 spread.
- This is a **single-process, single-node, laptop** figure. The obvious levers,
  none of which are applied here, in rough order of impact:
  1. `uvicorn --workers N` (the API is stateless);
  2. `executemany` / `COPY`-style bulk insert instead of ORM `add_all`;
  3. time-partition or roll up the telemetry tables (see
     [`limitations.md`](limitations.md));
  4. a dedicated ingestion path that writes to a Redis Stream and lets the
     worker batch-drain into Postgres, decoupling client latency from DB write
     latency;
  5. Postgres tuning (`shared_buffers`, `wal_writer_delay`, unlogged staging
     tables) and faster storage than a Docker Desktop volume.

The point of this platform is incident intelligence, not ingestion throughput;
2 k events/sec on a laptop is enough to run every demo scenario comfortably.
Run the script on your own target environment and record its conditions here.
