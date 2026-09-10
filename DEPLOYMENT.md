# Deploying Nirikshan on Render (free tier)

`render.yaml` in the repo root is a Render **Blueprint** that stands up four
resources on Render's free plan:

| Resource | Type | Notes |
|---|---|---|
| `nirikshan-db` | PostgreSQL (free) | **Render deletes free databases 30 days after creation.** |
| `nirikshan-kv` | Key Value / Redis (free) | ~25 MB, no persistence — fine; Postgres stays authoritative |
| `nirikshan-api` | Web service (Docker) | FastAPI + the event worker running **in-process** (`NIRIKSHAN_RUN_WORKER_IN_PROCESS=true`) |
| `nirikshan-web` | Web service (Docker) | Next.js dashboard; forwards `/api/*` to the API (same-origin, no CORS) |

### Known free-tier trade-offs
- Services **sleep after ~15 min idle** → first request takes ~50 s to wake.
- API instance is **512 MB RAM**; numpy/pandas/scikit-learn make this tight —
  an Isolation-Forest fit on a large window can OOM. The mock provider + normal
  demo load are fine.
- Free Postgres expires after 30 days — recreate it (and re-run the seed) or
  move that one resource to the $6/mo plan.

---

## 1. Push the branch and open the Blueprint

```bash
git push -u origin deploy/render      # or merge to main first
```

In the Render dashboard: **New → Blueprint**, pick the repo, choose the
`deploy/render` branch (or `main`). Render reads `render.yaml` and shows the four
resources. It will prompt once for any `sync: false` var:

- `NIRIKSHAN_LLM_API_KEY` — **leave blank** to use the built-in mock provider.
  To get real AI, paste a free [Groq](https://console.groq.com) API key and also
  set `NIRIKSHAN_LLM_PROVIDER=groq` + `NIRIKSHAN_LLM_MODEL=llama-3.3-70b-versatile`
  on `nirikshan-api` afterwards.

Click **Apply**. First build takes ~8–12 min (the API image compiles numpy/pandas).

## 2. Confirm the service URLs

Render gives each service `https://<name>.onrender.com` **if the name is free**.
If `nirikshan-api` / `nirikshan-web` were taken, Render appends random characters.

Check the actual API URL on the `nirikshan-api` service page, then on
`nirikshan-web` → **Environment**:

- `API_INTERNAL_BASE_URL` must equal the real API URL (e.g.
  `https://nirikshan-api-xxxx.onrender.com`). Fix it if needed and **Manual Deploy → Deploy latest commit**.

(Also update `NIRIKSHAN_CORS_ORIGINS` on the API to the real web URL. It only
matters if you call the API directly from a browser — the dashboard goes through
the same-origin proxy — but keep it correct.)

## 3. Get the admin login

`nirikshan-api` → **Environment** → reveal `NIRIKSHAN_BOOTSTRAP_ADMIN_PASSWORD`
(Render generated it). Log in at the web URL with:

```
admin@nirikshan.dev  /  <that value>
```

The API creates this user automatically on first boot.

## 4. Seed the demo data

The Blueprint does **not** run the seed container. Once the API is up, from your
machine:

```bash
API=https://nirikshan-api-xxxx.onrender.com
TOK=$(curl -s -X POST $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@nirikshan.dev","password":"<admin password>"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST $API/api/demo/seed -H "Authorization: Bearer $TOK"
curl -s -X POST $API/api/demo/run-scenario -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"db-exhaustion","investigate":true,"propose_remediation":true}'
```

Open the web URL → log in → the Overview shows a live SEV-1 incident with an AI
RCA. Re-run step 4 after the Postgres is recreated (30-day expiry) or any time
you want fresh demo data.

## 5. Later deploys

`autoDeploy: false` in the Blueprint means pushes don't redeploy automatically.
Use **Manual Deploy → Deploy latest commit** on each service, or flip
`autoDeploy` to `true`.

---

## Troubleshooting

- **API deploy fails at `alembic upgrade head` / "SSL required"** — add
  `?sslmode=require` to `NIRIKSHAN_DATABASE_URL` on `nirikshan-api` (Render's
  external Postgres string needs it; the internal one usually doesn't).
- **Web shows "Failed to fetch" / login hangs** — `API_INTERNAL_BASE_URL` on
  `nirikshan-web` doesn't match the real API URL. Fix and redeploy the web service.
- **502 for ~50 s then works** — normal free-tier cold start.
- **API restarts / "Out of memory"** — the free 512 MB is tight. Keep
  `NIRIKSHAN_LLM_PROVIDER=mock`, or upgrade `nirikshan-api` to Starter.
- **`relation "..." does not exist`** after 30 days — the free Postgres was
  deleted. Recreate the database resource and re-run step 4.

## Deploying elsewhere

The same knobs apply to any host:

| Env var | Purpose |
|---|---|
| `NIRIKSHAN_DATABASE_URL` | `postgres://` / `postgresql://` are accepted and rewritten to `postgresql+psycopg://` |
| `NIRIKSHAN_REDIS_URL` | `redis://` or `rediss://` |
| `NIRIKSHAN_SECRET_KEY` | 32+ random bytes (the API warns at boot otherwise) |
| `NIRIKSHAN_RUN_WORKER_IN_PROCESS` | `true` for single-service hosts; otherwise run `nirikshan-worker` separately |
| `NIRIKSHAN_ENV` | `production` |
| `PORT` | honoured by both images |
| web `NEXT_PUBLIC_API_BASE_URL` (build arg) | empty for the same-origin proxy; or an absolute API URL (then set `NIRIKSHAN_CORS_ORIGINS`) |
| web `API_INTERNAL_BASE_URL` | where the Next server forwards `/api/*` |

A dedicated `worker` process/container is preferred wherever you can run one —
set `NIRIKSHAN_RUN_WORKER_IN_PROCESS=false` (default) and start
`python -m nirikshan.workers`.
