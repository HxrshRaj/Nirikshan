# Limitations (honest)

## Remediation environment is simulated
`apply` / `revert` mutate a small runtime state machine on `Service.attributes`
(replica count, connection pool, feature flags, cache generation) and, for the
demo, a "suppressed fault" tag the telemetry generator reads to ramp a service
back to baseline. There is no Kubernetes/cloud integration. This is deliberate
(spec 30, 78) — the point is the *policy + approval + verification + rollback*
machinery, which is real. Wiring an executor to a real orchestrator is a
contained change: add registry entries whose `apply` calls a real client.

## Investigator control loop is a fixed playbook
The sequence of tool calls is deterministic Python, not model-driven. The model
does the synthesis. A true model-driven tool-use loop (with per-tool call
budgets and a max-iteration cap) is designed for but not implemented.

## Embeddings are lexical by default
`LocalHashEmbeddingProvider` is a hashed bag-of-token-bigrams projected to a
fixed unit vector — stable and offline, but retrieval is closer to keyword
overlap than deep semantic similarity. Set `NIRIKSHAN_EMBEDDING_PROVIDER=openai`
for real embeddings, or move to `pgvector`.

## Single-tenant data model
`Organization → Environment → Service` exists, but there is no auth scoping by
org/environment and no per-tenant isolation. Everything runs in one
`nirikshan / production` scope.

## Telemetry storage is unpartitioned
Metrics/logs/traces are plain indexed tables with a periodic delete-based
retention job. At real volume you would want native partitioning by time,
rollup tables, or TimescaleDB. Baseline recomputation on every anomaly scan is
the current hotspot — it should be incrementalised/cached.

## Real-time is SSE only
`/api/stream` mirrors the Redis pub/sub channel over Server-Sent Events; the UI
also polls. No WebSocket, no backpressure handling, no per-user event filtering.

## Alert rules are simple
Threshold + `for`-duration over one signal. No expression language, no
multi-condition rules, no `absent()`/`rate()` style functions. Enough to
demonstrate correct evaluation, not a Prometheus replacement (spec 16, 77).

## Type checking is partial
`mypy` runs in CI as advisory (`|| true`). Pydantic models and the domain layer
are well-typed; some ORM-heavy modules are not fully annotated.

## Cost figures are estimates
`ai/cost.py` uses a 4-chars/token heuristic and an approximate public price
table. It is for operational dashboards, never billing.

## No published benchmarks
`scripts/loadtest.py` exists but this repo quotes **no** throughput/latency
numbers — they are entirely host-dependent. Run it yourself and record the
conditions.

## Verified in this build
- 58 automated tests green (unit/e2e/failure/ai_eval on SQLite+fakeredis;
  integration on real PostgreSQL 16 + Redis 7).
- Alembic migration applies and round-trips (`upgrade → downgrade → upgrade`).
- Full pipeline exercised end-to-end through the HTTP API and the browser UI
  against both SQLite and real Postgres/Redis: seed → scenario → anomaly →
  alert → incident → investigation (RCA `database_saturation`, confidence 0.91)
  → remediation proposal → approve → execute → verify (3/3 checks) → resolve.
- AI evaluation harness passes its thresholds (rca_accuracy 1.0, hallucination
  0.0, unsafe 0.0, mean confidence error ~0.12).
- Frontend builds clean (Next.js, 16 routes) and renders live data.
- **Full `docker compose up --build` clean-start verified.** All four images
  build (`api`/`worker`/`seed` share a ~972 MB Python image; `nirikshan-web` is
  the Next.js standalone image). Startup order: `postgres → redis → api` (waits
  for the DB, runs `alembic upgrade head`, serves; reaches `healthy`) `→ worker
  → seed` (one-shot: migrates + seeds topology/telemetry/demo users, exits 0)
  `→ web` (`:3000` serves the dashboard). The full demo flow was then driven
  against the running stack over HTTP and in the browser: seed → scenario →
  anomaly → correlated alerts → SEV-1 incident → AI investigation
  (`database_saturation`, confidence 0.91) → remediation proposal → approve →
  execute → verify → incident `RESOLVED`; a `deploy-regression` run produced a
  recorded `ROLLED_BACK` deployment. `/api/metrics` exposes the platform's own
  gauges. (The Docker daemon on the dev machine was intermittently unavailable
  earlier in the session; the verification was completed once it recovered.)
