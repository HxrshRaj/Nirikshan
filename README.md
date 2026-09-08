# Nirikshan

**AI-Powered SRE & Incident Response Platform**

_Nirikshan_ (निरीक्षण) — "observation, monitoring, careful examination."

Nirikshan ingests application telemetry (logs, metrics, traces), correlates it
with deployments and a service dependency graph, detects incidents, runs an
**evidence-grounded AI investigation** that uses structured tools rather than raw
database access, and gates **safe, reversible remediation** behind human
approval and a policy engine. When the LLM is unavailable the platform keeps
detecting and managing incidents — the AI is an accelerator, never a
single point of failure.

---

## 1. Overview

| Capability | What it does |
|---|---|
| **Telemetry pipeline** | Validate → normalize → enrich (deployment id, correlation ids) → store → aggregate |
| **Anomaly detection** | z-score / EWMA / rolling-IQR against adaptive baselines; Isolation Forest cross-check for multi-modal metrics |
| **Alert engine** | Threshold + `for`-duration rules over metric / error-rate / latency / log / health signals |
| **Alert correlation** | Groups alerts on the same or dependency-linked service within a time window into one incident (dedup) |
| **Incident engine** | State machine (`DETECTED → INVESTIGATING → ACKNOWLEDGED → MITIGATING → RESOLVED → CLOSED`), timeline from stored facts, configurable severity scoring |
| **Blast radius** | BFS over the dependency graph — direct/indirect dependents, user-facing impact |
| **AI investigator** | Deterministic SRE playbook of audited tool calls → curated evidence bundle → provider synthesis → ranked hypotheses + RCA with confidence |
| **Incident memory / RAG** | Resolved incidents are embedded and retrieved as supporting context for similar future incidents |
| **Remediation agent** | Proposes exactly one *registered* safe action with rationale, risk, rollback plan and a metric-based verification plan |
| **Policy + approval** | Allowlist → parameter schema → risk vs. confidence → mode (`OBSERVE`/`RECOMMEND`/`APPROVAL_REQUIRED`/`AUTONOMOUS`) → RBAC gate → execute → verify → rollback |
| **AI observability** | Per-run tool calls, tokens, latency, estimated cost, prompt version, full audit trail |
| **AI evaluation harness** | Scores RCA correctness, evidence grounding, hallucination rate, confidence calibration, unsafe-recommendation rate on deterministic scenarios |

## 2. Problem

When something breaks, an engineer manually walks: alert → logs → metrics →
traces → recent deployments → dependency health → infrastructure → root cause →
remediation. Nirikshan compresses that loop by doing the structured
evidence-gathering automatically and presenting a ranked, **evidence-cited**
root-cause analysis plus a safe, reviewable fix.

Nirikshan is **not** a Datadog/Grafana/Prometheus replacement and **not** an
"LLM over a log file." The engineering problem it targets is: *how do you turn
distributed-system telemetry into reliable incident intelligence and safe
automation?*

## 3. Architecture

```
                       ┌──────────────────────┐
                       │   Next.js dashboard  │  (SSE live updates + polling)
                       └───────────┬──────────┘
                                   │ HTTPS / JWT
                       ┌───────────▼──────────┐
                       │      FastAPI API     │
                       │  auth · RBAC · audit │
                       │  rate limiting       │
                       └───┬──────────┬───────┘
              ┌────────────┘          └───────────────┐
              ▼                                       ▼
   Telemetry ingestion / query          Incident · AI · Remediation engines
              │                                       │
     ┌────────▼─────────┐                   ┌──────────▼───────────┐
     │   PostgreSQL     │◀── authoritative ─│  LLM / Embedding     │
     │  (28 tables)     │      state        │  provider abstraction│
     └────────┬─────────┘                   │  mock · openai · groq│
              │                             └──────────────────────┘
              │ events (Redis Streams)
     ┌────────▼─────────┐        ┌─────────────────────────────────┐
     │      Redis       │───────▶│  Worker: consume events         │
     │  streams · cache │        │  telemetry→anomaly→alert→        │
     │  rate limit·pubsub│       │  incident→investigation→         │
     └──────────────────┘        │  remediation proposal + retention│
                                 └─────────────────────────────────┘
```

Full detail: [`docs/architecture.md`](docs/architecture.md).

## 4. Key features

See table in §1. Highlights that matter in an interview:

- **Tools, not the database.** The investigator's control loop is explicit
  Python (an SRE playbook). Each evidence source is a named, typed, logged tool
  call (`query_metrics`, `search_logs`, `get_recent_deployments`,
  `get_dependencies`, `get_related_incidents`, …). The model only ever sees the
  curated, provenance-tagged evidence bundle — never raw rows, connection
  strings, secrets, or other data. See [`docs/ai-investigation.md`](docs/ai-investigation.md).
- **Grounded RCA.** Every hypothesis must cite evidence ids that exist in the
  bundle. Uncited claims from a remote model are dropped and the confidence is
  capped; the mock reasoner is grounded by construction. Hallucination rate is
  measured by the eval harness and gated in CI.
- **The AI cannot act.** `AI → structured tool → policy → permission → approval
  → execution`. There is no code path from model output to a shell command;
  actions are an explicit registry of demo-environment operations with typed
  parameters. See [`docs/remediation.md`](docs/remediation.md).
- **Degrades gracefully.** LLM down → investigation marked `FAILED`, retryable,
  incident untouched. Redis down → a circuit breaker trips, events are dropped,
  rate limiting fails open, the API stays online. Postgres is the only hard
  dependency.

## 5. Telemetry pipeline

`POST /api/telemetry/{logs,metrics,traces}` (single object or batch). Stages:
validation (Pydantic + semantic rules) → normalization (default/clamp
timestamps, lower-case names) → enrichment (resolve environment/service,
auto-register unknown services at tier 3 so nothing is dropped, attach the most
recent deployment id) → bulk storage → `TELEMETRY_RECEIVED` event. Malformed
rows are skipped and counted, never fatal to the batch. Retention is enforced
periodically by the worker (configurable per signal type).

## 6. Incident engine

Alerts are correlated (`detection/correlation.py`) into a new or existing open
incident. Severity (`incidents/severity.py`) is a weighted score over service
tier, alert severity, correlated-alert count, error-rate/latency multiple of
SLO, blast radius and hard-dependency outage → `SEV-1..4`. The timeline
(`incident_events`) is built only from stored facts. State transitions are
validated against `INCIDENT_TRANSITIONS`.

## 7. Anomaly detection

`detection/baseline.py` keeps a running per-`(service, metric)` summary (mean/std,
EWMA/EWVAR, p50/p95) recomputed from history **excluding the window under test**
so an in-progress incident can't poison the reference distribution. A point is
flagged only if it is both statistically extreme (z ≥ 3.5) **and** sustained
over several consecutive samples. Drops in "higher-is-worse" metrics are
suppressed.

## 8. Service dependency graph

Directed edges (`service_dependencies`), loaded once per request into an
in-memory adjacency map. Powers correlation, blast-radius BFS, and a
"most-probable-root" heuristic (a service many impacted services transitively
depend on ranks above a leaf).

## 9. AI investigation

```
incident ──▶ gather evidence (audited tools) ──▶ evidence bundle
        ──▶ provider.analyze(bundle, prompt)   (mock | openai | groq)
        ──▶ validate + ground (drop uncited, clamp confidence)
        ──▶ persist evidence rows + ranked hypotheses + RCA
        ──▶ INVESTIGATION_COMPLETED   (or FAILED, retryable)
```

The `AgentRun` row records: prompt name+version+checksum, provider/model,
`is_mock`, every tool call (args, ok, rows, summary, duration), tokens, latency,
estimated cost, grounded vs. available evidence ids, and warnings.

## 10. Evidence-based RCA

Each RCA carries: root cause, calibrated confidence (0–1), summary, contributing
factors, recommended actions, affected services, the evidence it is grounded in,
and the ranked hypotheses. Mock output is always labelled **"Demo / Mock
Provider"** in the API and UI and is never presented as production analysis.

## 11. RAG / incident memory

On close, an incident is distilled into a `HistoricalIncident` document with an
embedding (provider-abstracted; deterministic local hash embedding by default so
it works offline / in CI). The `get_related_incidents` tool retrieves the top-k
by cosine similarity as supporting context.

## 12. Remediation engine

Registry of demo-environment actions: `rollback_demo_deployment`,
`scale_demo_service`, `restart_demo_service`, `disable_demo_feature_flag`,
`clear_demo_cache`. Each has a typed parameter schema, default risk,
reversibility, minimum role, and typed `apply` / `revert` functions that mutate
runtime state stored on `Service.attributes` (observable, shared across
processes). Verification re-reads telemetry and compares against the plan's
metric checks and the learned baseline.

## 13. Human-in-the-loop

Default mode is `APPROVAL_REQUIRED`. The policy engine returns `allowed_now`,
`requires_approval`, `min_role` and findings. `AUTONOMOUS` only auto-executes
`LOW`-risk, reversible actions with RCA confidence ≥ 0.8; everything else still
needs a human. Approvals/rejections/executions/rollbacks are all recorded.

## 14. Security

JWT access/refresh tokens (HS256), bcrypt password hashing, RBAC
(`VIEWER < ENGINEER < INCIDENT_COMMANDER < ADMIN`) enforced on the backend,
audit log with secret scrubbing, Redis fixed-window rate limiting on telemetry /
investigation / remediation endpoints (fails open), structured error envelope,
no secrets exposed to the AI, action allowlist. See [`docs/security.md`](docs/security.md).

## 15. API

OpenAPI at `/docs`. Route list in [`docs/api.md`](docs/api.md). Consistent
`{code, message, details}` error envelope; every response carries `x-request-id`.

## 16. Database

PostgreSQL, 28 tables with foreign keys, composite indexes on the dominant read
paths, constraints, and JSON columns only where the shape is genuinely dynamic
(evidence data, audit before/after, agent audit trail). Schema is managed by
Alembic (`alembic upgrade head`); `create_all()` is used for tests and
zero-config local runs. SQLite is supported for isolated unit tests only.

## 17. Redis

Redis Streams carry the event fan-out to the worker; a consumer group with
explicit `XACK` gives at-least-once processing. Also used for the SSE pub/sub
channel, response caching and rate-limit counters. A circuit breaker stops
hammering a dead Redis (each call would otherwise pay the socket timeout).
PostgreSQL remains authoritative — Redis loss degrades liveness, not
correctness.

## 18. Docker

`docker compose up --build` starts `postgres`, `redis`, `api`, `worker`, a
one-shot `seed`, and `web`. The API container waits for the DB, runs
`alembic upgrade head`, then serves. Images run as non-root with healthchecks.

```bash
cp .env.example .env            # optional; sane defaults otherwise
docker compose up --build       # api :8000, web :3000
# then: log in as admin@nirikshan.dev / admin12345, open Settings → seed + run a scenario
```

## 19. Testing

```bash
pip install -e ".[dev]"
pytest -q -m "not integration"          # unit · e2e · failure · ai_eval (SQLite + fakeredis)
# integration (real services):
docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=nirikshan -e POSTGRES_USER=nirikshan -e POSTGRES_DB=nirikshan postgres:16-alpine
docker run -d -p 56379:6379 redis:7-alpine
NIRIKSHAN_TEST_DATABASE_URL=postgresql+psycopg://nirikshan:nirikshan@localhost:55432/nirikshan \
NIRIKSHAN_TEST_REDIS_URL=redis://localhost:56379/15 pytest -q -m integration
```

Markers: `unit`, `integration`, `e2e`, `ai_eval`, `failure`. Coverage of anomaly
algorithms, alert rules, the incident state machine, correlation/dedup, the
dependency graph + blast radius, remediation policy + RBAC, AI guardrails
(uncited-evidence drop, disallowed-action rejection), auth/tokens, telemetry
validation; full-scenario pipeline and HTTP-flow e2e; fault injection (AI
timeout, malformed AI output, duplicate alerts, unauthorized remediation, Redis
outage). See [`docs/testing.md`](docs/testing.md).

## 20. AI evaluation

```bash
python evaluation/run_eval.py           # exits non-zero if thresholds fail (CI gate)
```

Runs each deterministic scenario in an isolated database and scores the
investigator: `rca_accuracy` (must be 1.0 on the deterministic set),
`mean_evidence_grounding` (≥ 0.6), `hallucination_rate` (0.0),
`mean_confidence_error` (≤ 0.35), `unsafe_recommendation_rate` (0.0).
"The LLM returned an answer" is never treated as success.

## 21. Load testing

`scripts/loadtest.py` drives batched telemetry ingestion and reports
events/sec and ingestion latency. Numbers depend entirely on the host and are
**not** published here — run it against your own environment and record the
conditions.

## 22. Demo scenarios

| Scenario | Injects | Expected RCA category |
|---|---|---|
| `normal` | healthy traffic | *(no incident)* |
| `db-exhaustion` | Payment saturates the PG connection pool | `database_saturation` |
| `deploy-regression` | Order Service deploy `v2.4.0` + error spike | `deployment_regression` |
| `dependency-failure` | PostgreSQL unhealthy → Payment degrades | `upstream_dependency_failure` |
| `traffic-spike` | Notification queue overload | `traffic_overload` |

`python -m nirikshan.demo scenario db-exhaustion --remediate` runs the whole
loop (detect → investigate → propose → approve → execute → advance demo clock →
verify recovery → resolve) in seconds.

## 23. Distributed-system considerations

- **Consistency:** PostgreSQL is authoritative; all incident/remediation state
  changes are single-transaction. Events are at-least-once (consumer group +
  `XACK`); handlers are idempotent (fingerprint dedup, `run_id` guards).
- **Failure isolation:** LLM, Redis and the worker can each be down without
  losing incident data. The API only hard-depends on Postgres.
- **Scaling path:** stateless API replicas behind a load balancer; multiple
  worker consumers in the same group; Postgres read replicas for the telemetry
  read paths; partition/rollup telemetry tables by time; move embeddings to
  `pgvector`. Biggest bottleneck today is per-metric baseline recomputation on
  every anomaly scan — cache/incrementalize it.

## 24. Limitations

See [`docs/limitations.md`](docs/limitations.md). In brief: the remediation
"environment" is a simulated demo state machine, not real infrastructure; the
default embedding is a hash bag-of-words (retrieval is lexical, not deeply
semantic); telemetry is single-tenant / single-org in the data model; the
investigator's control loop is a fixed playbook rather than a model-driven tool
loop; no time-series partitioning yet; SSE only (no WebSocket); type coverage
(`mypy`) is partial and advisory in CI.

## 25. Future work

Model-driven tool-use loop with per-tool budgets; `pgvector` embeddings;
multi-environment/multi-org tenancy; TimescaleDB or native partitioning for
telemetry; richer alert-rule expressions; on-call routing / paging integration;
WebSocket transport; PII redaction in the log-search tool; replay-based eval
against real historical incidents.

---

## Repository layout

```
nirikshan/
├── src/nirikshan/
│   ├── core/         config, logging, db, redis bus (+ circuit breaker), events, errors
│   ├── domain/       shared enums + the incident state-transition table
│   ├── models/       SQLAlchemy ORM (28 tables) + portable UTC datetime type
│   ├── schemas/      Pydantic request/response models
│   ├── catalog/      org→env→service topology, dependency graph + blast radius
│   ├── telemetry/    ingestion pipeline, query (log search / metric series / traces), aggregation, retention
│   ├── detection/    baselines, anomaly detection, alert-rule engine, alert→incident correlation
│   ├── incidents/    lifecycle engine, severity scoring, incident memory / RAG
│   ├── ai/           provider abstraction, mock reasoner/planner, tools, investigator, remediation agent, prompts, cost, evaluation
│   ├── remediation/  action registry (sandbox), policy engine, executor, verification, rollback
│   ├── security/     passwords, JWT, users, RBAC deps, audit, rate limiting
│   ├── api/          FastAPI app, routers, serializers, SSE
│   ├── workers/      event consumer loop + handlers + periodic maintenance
│   └── demo/         topology, deterministic telemetry generator, scenarios, remediation flow
├── apps/web/         Next.js dashboard (App Router, Tailwind)
├── migrations/       Alembic
├── evaluation/       AI evaluation harness runner
├── tests/            unit · integration · e2e · failure · ai_eval
├── docs/             architecture, ai-investigation, incident-lifecycle, remediation, security, api, testing, limitations
├── infrastructure/   container entrypoint
├── .github/workflows/ci.yml
├── Dockerfile · docker-compose.yml · alembic.ini · pyproject.toml · .env.example
```

## Git / attribution

Authored by **Harsh Raj** (<https://github.com/HxrshRaj>). This repository is not
auto-committed or pushed.
