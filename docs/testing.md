# Testing

```bash
pip install -e ".[dev]"

pytest -q -m "not integration"      # unit + e2e + failure + ai_eval  (SQLite in-memory + fakeredis)
pytest -q -m integration            # requires real Postgres + Redis (see below)
python evaluation/run_eval.py       # AI evaluation harness (CI gate)
ruff check src tests evaluation
```

## Markers

| Marker | Scope | Backing services |
|---|---|---|
| `unit` | algorithms & pure logic in isolation | SQLite `:memory:`, `fakeredis` |
| `e2e` | full scenario pipeline + HTTP flow | SQLite `:memory:`, `fakeredis` |
| `failure` | fault injection / resilience | SQLite `:memory:`, `fakeredis` |
| `ai_eval` | evaluation harness thresholds | SQLite `:memory:`, `fakeredis` |
| `integration` | real Postgres + Redis, Streams, concurrency | **real** containers |
| Playwright | frontend E2E (login, dashboards, RBAC, RCA UI) | live `docker compose` stack |

## What is covered

**Unit** — baseline excludes the window under test; z-score anomaly on a
sustained spike; no anomaly on a steady series; single blip suppressed; alert
rule fires after dwell + is deduped; rule resolves when the condition clears;
incident created from an alert; second alert correlates (not a new incident);
duplicate fingerprint doesn't double-count; illegal state transition rejected;
happy-path transitions stamp timestamps; blast radius (direct/indirect/
user-facing/total); downstream closure; most-probable-root heuristic; severity
SEV-1 vs SEV-4; policy blocks a non-allowlisted action; policy requires approval
in default mode; mock reasoner identifies DB saturation / deployment regression /
inconclusive; validation drops uncited evidence; disallowed action rejected;
password hash round-trip; token type / tamper rejection; audit secret scrub;
telemetry auto-registers services, rejects non-finite metrics, survives a bad
row, clamps future timestamps.

**E2E** — each of the 4 fault scenarios produces the correct incident + RCA
category + confidence + a proposed remediation, backed by stored evidence and a
selected top hypothesis; `normal` produces no incident; the full remediation
loop (approve → execute → advance demo clock → verify → resolve) succeeds and
archives to incident memory; re-investigation is idempotent (no duplicated
evidence/hypotheses). HTTP: login → seed → scenario → incident detail → RCA
(`is_mock` flagged) → timeline → drive-remediation → RESOLVED; a VIEWER gets 403
on mutating endpoints and the audit log; unauthenticated calls get 401.

**Failure** — AI timeout preserves the incident, marks the run FAILED
(retryable), and a retry with a working provider completes; malformed AI output
is rejected; 4× repeated payment alerts → exactly 1 incident; a VIEWER approving
remediation raises `PermissionError_`; a broken event bus does not stop
telemetry storage; the Redis circuit breaker opens and stops hammering a dead
Redis.

**Integration** (real services) — full pipeline on Postgres; Redis Streams
publish/read/ack round-trip; the worker's `drain()` turns a `TELEMETRY_RECEIVED`
event into an incident using its own sessions; two sessions acknowledging the
same incident stay consistent.

## Frontend E2E (Playwright)

```bash
docker compose up -d --wait api web worker
# seed one incident (see the `e2e` CI job for the exact curl calls)
cd apps/web && npm ci && npx playwright install --with-deps chromium
npm run e2e            # or: npm run e2e:ui
```

`e2e/dashboard.spec.ts` asserts: login + overview stat tiles + demo topology;
incident-detail RCA block, ranked hypotheses, evidence panel, timeline and the
"Demo / Mock Provider" label; the service-map SVG; the AI-run page's tool-call
audit trail and grounding panel; and that a `VIEWER` sees the "requires ADMIN"
gate on Settings. Screenshots land in `apps/web/e2e/screenshots/` (a curated
copy is in `docs/screenshots/`). The `e2e` CI job runs this against a freshly
built compose stack.

## Running integration locally

```bash
docker run -d --name nk-pg  -p 55432:5432 \
  -e POSTGRES_USER=nirikshan -e POSTGRES_PASSWORD=nirikshan -e POSTGRES_DB=nirikshan postgres:16-alpine
docker run -d --name nk-redis -p 56379:6379 redis:7-alpine

NIRIKSHAN_TEST_DATABASE_URL=postgresql+psycopg://nirikshan:nirikshan@localhost:55432/nirikshan \
NIRIKSHAN_TEST_REDIS_URL=redis://localhost:56379/15 \
pytest -q -m integration
```

CI (`.github/workflows/ci.yml`) provides both as service containers and also
runs `alembic upgrade head → downgrade base → upgrade head`, the non-integration
suite with coverage, the integration suite, and the evaluation harness.

## Regression policy

Every bug found gets a test in the matching module before the fix is considered
done. Example already in the tree: `test_redis_circuit_breaker_stops_hammering`
was added after discovering that a dead Redis added its socket timeout to every
request.
