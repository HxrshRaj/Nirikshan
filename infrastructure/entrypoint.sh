#!/usr/bin/env sh
# Nirikshan container entrypoint.
#   api    -> wait for DB, run migrations, start uvicorn
#   worker -> wait for DB, start the event worker
#   demo   -> wait for DB, run migrations, seed the demo environment
#   *      -> exec whatever was passed
set -eu

wait_for_db() {
  python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
url = os.environ.get("NIRIKSHAN_DATABASE_URL", "")
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
if url.startswith("postgresql://"):
    url = "postgresql+psycopg://" + url[len("postgresql://"):]
if not url or url.startswith("sqlite"):
    sys.exit(0)
for i in range(60):
    try:
        create_engine(url).connect().execute(text("SELECT 1"))
        print("database is ready")
        sys.exit(0)
    except Exception as exc:  # noqa
        print(f"waiting for database ({i})... {exc}")
        time.sleep(2)
print("database not reachable", file=sys.stderr)
sys.exit(1)
PY
}

migrate() {
  echo "running alembic upgrade head"
  alembic upgrade head
}

case "${1:-api}" in
  api)
    wait_for_db
    migrate
    exec uvicorn nirikshan.api.app:app \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    wait_for_db
    exec python -m nirikshan.workers  # runs the consumer + maintenance loop
    ;;
  demo)
    wait_for_db
    migrate
    exec python -m nirikshan.demo seed
    ;;
  *)
    exec "$@"
    ;;
esac
