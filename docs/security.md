# Security

## Authentication

- JWT access + refresh tokens (HS256, `NIRIKSHAN_SECRET_KEY`). Access TTL 60 min,
  refresh 30 days (configurable). `require: ["exp", "sub"]` on decode; token
  type is checked (`access` vs `refresh`).
- Passwords: bcrypt, cost 12, 72-byte truncation handled.
- `POST /api/auth/login` / `/refresh` / `/logout` / `GET /api/auth/me`.
- A bootstrap admin is created on first boot from
  `NIRIKSHAN_BOOTSTRAP_ADMIN_{EMAIL,PASSWORD}` **only if no users exist**
  (dev convenience). Demo users (one per role) are created by `demo/seed`.

## Authorization

`VIEWER < ENGINEER < INCIDENT_COMMANDER < ADMIN`, enforced on the backend via
`Depends(require_role(...))` — never only in the UI.

| Capability | Minimum role |
|---|---|
| Read incidents / services / telemetry / agents | VIEWER |
| Acknowledge / resolve / investigate an incident; create alert rules; record deployments; propose remediation | ENGINEER |
| Approve / reject / rollback remediation; close an incident; read the audit log | INCIDENT_COMMANDER |
| Manage users; create services/dependencies; seed / run demo scenarios | ADMIN |

## Audit logging

`security/audit.record()` writes an immutable `audit_logs` row (actor,
actor_role, action, resource, result, ip, before/after, note) for: login
(success + failure), incident acknowledge/resolve/close/investigate, remediation
propose/approve/reject/rollback, user create/update, service/dependency create,
demo seed / scenario / drive-remediation. Sensitive keys
(`password`, `token`, `secret`, `api_key`, `authorization`, …) are scrubbed to
`***` in before/after.

## Telemetry ingestion

`POST /api/telemetry/{logs,metrics,traces}` are **not** behind user auth — real
telemetry collectors don't have a user session. Protection:

- Pydantic + semantic validation on every row; malformed rows are skipped and
  counted, never fatal.
- Per-identity rate limiting (`telemetry`, 2000/60s).
- Optional shared secret: set `NIRIKSHAN_INGEST_TOKEN` and every ingestion call
  must carry a matching `X-Ingest-Token` header (constant-time compare).
  Unset (the default) means open ingestion — acceptable for the local demo,
  not for a shared deployment.

In production you would additionally scope ingestion by network policy and/or
per-collector API keys.

## Rate limiting

Redis fixed-window counters (`security/ratelimit.py`) on:
`telemetry` (2000/60s), `investigate` (10/60s), `remediation` (20/60s),
`default` (300/60s). Identity is the user id, or client IP for unauthenticated
calls. **Fails open** if Redis is unavailable — availability of the core
platform beats strict limiting.

## AI safety boundary

- The model never receives raw DB access, DSNs, or secrets — only the curated
  evidence bundle from audited tools.
- The model cannot execute anything: proposals are validated against a static
  action allowlist + parameter schema, then the policy engine + RBAC, then a
  human.
- Output validation drops uncited evidence and caps ungrounded confidence.
- Every LLM call is logged to `llm_calls` (provider, model, tokens, latency,
  cost, ok/error) — no prompt/response bodies with secrets.

## Input handling

- Pydantic at the edge for every request body; semantic rules in the ingestion
  pipeline (finite metric values, non-blank log messages, clock-skew clamping,
  batch-size caps).
- Consistent `{code, message, details}` error envelope; unhandled exceptions
  return a generic 500 (details logged, not leaked).
- CORS origins are an explicit allowlist (`NIRIKSHAN_CORS_ORIGINS`).

## Secrets

`.env` is git-ignored; only `.env.example` is committed. The platform boots and
runs fully without any AI credentials (mock provider). CI uses throwaway
secrets. `pip-audit` runs in CI (advisory).

## Known gaps

Single-tenant data model; no PII redaction in the log-search tool; no
brute-force lockout beyond the login rate limit; `mypy` coverage is partial and
advisory. See [`limitations.md`](limitations.md).
