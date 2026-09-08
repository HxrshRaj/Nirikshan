# API

Base URL `http://localhost:8000`. OpenAPI/Swagger at `/docs`, ReDoc at `/redoc`.
All responses carry `x-request-id` and `x-response-time-ms`. Errors are
`{ "code": str, "message": str, "details": object }`.

Auth: `Authorization: Bearer <access_token>` on everything except
`/api/health`, `/api/metrics`, `/api/auth/login`, `/api/auth/refresh`.

## Auth
```
POST   /api/auth/login            {email, password} -> {access_token, refresh_token, expires_in}
POST   /api/auth/refresh          {refresh_token}
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/users                 (ADMIN)
POST   /api/users                 (ADMIN) {email, password, full_name, role}
PATCH  /api/users/{id}            (ADMIN)
```

## Telemetry
```
POST   /api/telemetry/logs        LogIn | {logs: [LogIn]}      (rate-limited)
POST   /api/telemetry/metrics     MetricIn | {metrics: [...]}  (rate-limited)
POST   /api/telemetry/traces      TraceIn | {traces: [...]}    (rate-limited)
GET    /api/logs                  ?service&level&min_level&query&trace_id&minutes&limit&offset
GET    /api/logs/histogram        ?service&minutes&buckets
GET    /api/metrics/series        ?service&metric&minutes&step_seconds&aggregation
GET    /api/metrics/names         ?service
GET    /api/traces                ?service&only_errors&minutes&limit
GET    /api/traces/{trace_id}
```

## Catalog
```
GET    /api/services                            GET /api/services/{name}
POST   /api/services              (ADMIN)        GET /api/services/{name}/health
GET    /api/services/{name}/blast-radius
GET    /api/dependencies                         POST /api/dependencies (ADMIN)
GET    /api/service-map           (graph + live health + open-incident counts)
```

## Deployments
```
GET    /api/deployments           ?service&limit
POST   /api/deployments           (ENGINEER) DeploymentIn
```

## Alerting
```
GET    /api/alerts                ?state&service&limit        GET /api/alerts/{ref}
GET    /api/alerts/rules                                      POST /api/alerts/rules (ENGINEER)
GET    /api/anomalies             ?service&minutes&limit
```

## Incidents
```
GET    /api/incidents             ?status&severity&service&open_only&limit&offset
GET    /api/incidents/{ref}
GET    /api/incidents/{ref}/timeline
GET    /api/incidents/{ref}/evidence
GET    /api/incidents/{ref}/rca
POST   /api/incidents/{ref}/acknowledge     (ENGINEER)
POST   /api/incidents/{ref}/resolve         (ENGINEER)
POST   /api/incidents/{ref}/close           (INCIDENT_COMMANDER)
POST   /api/incidents/{ref}/investigate     (ENGINEER, rate-limited) {force?, prompt_version?}
POST   /api/incidents/{ref}/remediation     (ENGINEER, rate-limited) {force?}
```

## Remediations
```
GET    /api/remediations                 ?status          GET /api/remediations/{ref}
GET    /api/remediations/actions          (allowlist + schemas)
POST   /api/remediations/{ref}/approve    (INCIDENT_COMMANDER)  -> approves + executes
POST   /api/remediations/{ref}/reject     (INCIDENT_COMMANDER)
POST   /api/remediations/{ref}/verify     (ENGINEER)
POST   /api/remediations/{ref}/rollback   (INCIDENT_COMMANDER)
```

## Agents / AI ops
```
GET    /api/agents                ?kind&incident_id&status&limit
GET    /api/agents/{run_id}       (full audit trail: tools, tokens, grounding, warnings)
GET    /api/agents/ops/summary    ?hours    (cost / latency / tool-call rollup)
```

## Observability
```
GET    /api/health                (public)
GET    /api/metrics               (public, Prometheus text format)
GET    /api/overview              (dashboard rollup)
GET    /api/audit                 (INCIDENT_COMMANDER) ?resource_type&resource_id&actor&limit&offset
GET    /api/stream                (SSE: mirrors the Redis live channel)
```

## Demo
```
GET    /api/demo/scenarios
POST   /api/demo/seed             (ADMIN)   topology + baseline telemetry + demo users
POST   /api/demo/run-scenario     (ADMIN)   {scenario, investigate, propose_remediation}
POST   /api/demo/drive-remediation(INCIDENT_COMMANDER) {incident_ref, scenario}  full loop
```
