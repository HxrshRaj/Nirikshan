# Deploying Nirikshan on Render (free tier)

`render.yaml` is a Render **Blueprint**. Render runs only the two Docker web
services (no per-account limit); PostgreSQL and Redis come from external free
providers so we dodge Render's "one free database per account" cap and the
30-day free-Postgres expiry.

| Piece | Provider | Notes |
|---|---|---|
| `nirikshan-api` | Render web service (Docker, free) | FastAPI + the event worker running **in-process** (`NIRIKSHAN_RUN_WORKER_IN_PROCESS=true`) |
| `nirikshan-web` | Render web service (Docker, free) | Next.js dashboard; forwards `/api/*` to the API (same-origin, no CORS) |
| PostgreSQL | **[Neon](https://neon.tech)** free | 0.5 GB, no expiry, no card. **Required** (Postgres is the only hard dependency). |
| Redis | **[Upstash](https://upstash.com)** free | no card. **Optional** — without it the API still serves the full synchronous demo; you lose the reactive worker pipeline + live SSE. |

### Known free-tier trade-offs
- Render services **sleep after ~15 min idle** → first request takes ~50 s.
- API instance is **512 MB RAM**; numpy/pandas/scikit-learn make this tight — an
  Isolation-Forest fit on a large window can OOM. Mock provider + demo load are fine.

---

## Branch model

Do **all** work on `main`. A GitHub Action
(`.github/workflows/mirror-deploy-branch.yml`) auto-fast-forwards `deploy/render`
to every `main` commit, so Render can stay pointed at `deploy/render` (or `main`
— either works, they're identical). `autoDeploy` is off; you ship with **Manual
Deploy → Deploy latest commit** on `nirikshan-api` and `nirikshan-web`.

## 1. Create the database (Neon) — required

1. [neon.tech](https://neon.tech) → sign in with GitHub → **New Project**
   (name it `nirikshan`, region close to Render's Oregon).
2. On the project dashboard, copy the **connection string** (Pooled connection).
   It looks like `postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/nirikshan?sslmode=require`.
   Nirikshan rewrites the scheme to `postgresql+psycopg://` automatically.

## 2. Create Redis (Upstash) — optional

1. [upstash.com](https://upstash.com) → sign in with GitHub → **Create Database**
   (Redis, region close to Oregon, free plan).
2. Copy the connection string from the **Redis** section — the `rediss://...`
   one (TLS). If you skip this, leave `NIRIKSHAN_REDIS_URL` blank.

## 3. Apply the Blueprint

Render dashboard → **New → Blueprint** → pick the repo → branch `deploy/render`
(or `main`). Render reads `render.yaml` and shows the two web services. It
prompts for the `sync: false` vars:

| Var | Value |
|---|---|
| `NIRIKSHAN_DATABASE_URL` | the Neon connection string from step 1 |
| `NIRIKSHAN_REDIS_URL` | the Upstash `rediss://` string from step 2, or leave blank |
| `NIRIKSHAN_LLM_API_KEY` | leave blank (mock provider). For real AI, paste a free [Groq](https://console.groq.com) key and set `NIRIKSHAN_LLM_PROVIDER=groq`, `NIRIKSHAN_LLM_MODEL=llama-3.3-70b-versatile` on `nirikshan-api` after. |

**Apply.** First build ~8–12 min (the API image compiles numpy/pandas).

> Already tried the old Blueprint and it half-failed on `nirikshan-db`? Just
> re-sync the Blueprint after this `render.yaml` lands — with no `databases:`
> block Render stops trying to create one, creates `nirikshan-api`, and updates
> `nirikshan-web`.

## 4. Confirm the service URLs

Render gives `https://<name>.onrender.com` if the name is free, else it appends
random chars. Check the real API URL on `nirikshan-api`, then on `nirikshan-web`
→ **Environment**: `API_INTERNAL_BASE_URL` must equal it. Fix + **Manual Deploy →
Deploy latest commit** if not. (Also set `NIRIKSHAN_CORS_ORIGINS` on the API to
the real web URL — only matters for direct API calls, but keep it correct.)

## 5. Get the admin login

`nirikshan-api` → **Environment** → reveal `NIRIKSHAN_BOOTSTRAP_ADMIN_PASSWORD`
(Render generated it). The API creates this user on first boot:

```
admin@nirikshan.dev  /  <that value>
```

## 6. Seed the demo data

Once the API is healthy, from your machine:

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
RCA. Re-run this any time you want fresh demo data.

## 7. Later deploys

Push to `main` → the mirror updates `deploy/render` → **Manual Deploy → Deploy
latest commit** on Render. Flip `autoDeploy` to `true` in `render.yaml` for
push-to-deploy.

---

## Troubleshooting

- **API deploy fails at `alembic upgrade head` / "SSL required"** — make sure the
  Neon string keeps `?sslmode=require` (it does by default).
- **`password authentication failed` / can't connect to Neon** — you copied the
  direct string but Neon suspended the endpoint; use the **Pooled** connection
  string, and confirm the project isn't paused.
- **Web shows "Failed to fetch" / login hangs** — `API_INTERNAL_BASE_URL` on
  `nirikshan-web` ≠ the real API URL. Fix and redeploy the web service.
- **502 for ~50 s then works** — normal free-tier cold start.
- **API "Out of memory" / restarts** — free 512 MB is tight. Keep
  `NIRIKSHAN_LLM_PROVIDER=mock`, or bump `nirikshan-api` to Starter.
- **No live updates, no auto-incidents from telemetry** — `NIRIKSHAN_REDIS_URL`
  is blank/unreachable. Expected; the `/run-scenario` flow still works. Add
  Upstash to enable the reactive pipeline.

## Deploying elsewhere

| Env var | Purpose |
|---|---|
| `NIRIKSHAN_DATABASE_URL` | `postgres://` / `postgresql://` accepted, rewritten to `postgresql+psycopg://` |
| `NIRIKSHAN_REDIS_URL` | `redis://` or `rediss://`; blank = degrade gracefully |
| `NIRIKSHAN_SECRET_KEY` | 32+ random bytes (API warns at boot otherwise) |
| `NIRIKSHAN_RUN_WORKER_IN_PROCESS` | `true` for single-service hosts; else run `nirikshan-worker` separately |
| `NIRIKSHAN_ENV` | `production` |
| `PORT` | honoured by both images |
| web `NEXT_PUBLIC_API_BASE_URL` (build arg) | empty for the same-origin proxy; or an absolute API URL (then set `NIRIKSHAN_CORS_ORIGINS`) |
| web `API_INTERNAL_BASE_URL` | where the Next server forwards `/api/*` |

A dedicated `worker` process is preferred where you can run one — set
`NIRIKSHAN_RUN_WORKER_IN_PROCESS=false` and run `python -m nirikshan.workers`.
