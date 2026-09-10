# Contributing

## Setup

```bash
make venv && make install          # Python: .venv + package + dev extras
make web-install                   # dashboard deps
cp .env.example .env               # optional; sane defaults otherwise
```

## Everyday commands

| Task | Command |
|---|---|
| Full stack (Docker) | `make up` → api :8000, web :3000; `make down` |
| Lint | `make lint` |
| Type check (advisory) | `make typecheck` |
| Tests (fast) | `make test` |
| Integration tests | `make up` then `make test-int` |
| AI evaluation harness | `make eval` |
| Seed demo / run a scenario | `make seed` / `make scenario KEY=db-exhaustion` |
| Frontend build / E2E | `make web-build` / `make web-e2e` |

## Conventions

- **PostgreSQL is authoritative.** SQLite is for isolated unit tests only.
  Schema changes go through Alembic:
  `alembic revision --autogenerate -m "..."` then review the generated file
  (the `render_item` hook renders `UTCDateTime` as `sa.DateTime(timezone=True)`).
- **Every bug fix ships with a regression test** in the matching `tests/`
  module. New behaviour needs `unit` coverage; pipeline behaviour needs `e2e`.
- **The AI never executes anything.** Model output may only *name* a registered
  action (`nirikshan/remediation/registry.py`) with typed parameters, which then
  passes the policy engine + RBAC + human approval. No `eval`/`exec`/`subprocess`.
- **Never fabricate** telemetry, metrics, RCA, tool calls, remediation results
  or benchmarks. Mock-provider output is always labelled "Demo / Mock Provider".
- Keep `ruff check` clean. Line length is not enforced but keep it sane.

## CI

`.github/workflows/ci.yml` runs on every push/PR: ruff, mypy (advisory),
Alembic up/down/up, the Python test suite with coverage, integration tests on
real Postgres + Redis service containers, the AI eval harness, both Docker image
builds, and the frontend lint/type/build. A heavyweight Playwright E2E job
against the compose stack is available on a manual **Run workflow** trigger.
