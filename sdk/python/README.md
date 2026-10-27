# nirikshan-sdk (Python)

Capture errors in your app and send them to a [Nirikshan](../../README.md) server. Standard library only, no dependencies.

```python
import nirikshan_sdk as nk

nk.init("https://your-nirikshan/api/telemetry/logs", "checkout-api",
        environment="production", release="2.0.1", ingest_token="...")

try:
    charge(order)
except Exception:
    nk.capture_exception()          # sends type, message, stack frames, fingerprint, breadcrumbs, tags

nk.set_tag("region", "ap-south-1")
nk.add_breadcrumb("payment started", category="payments")
nk.capture_message("cart abandoned", level="warning")
```

Unhandled exceptions (main thread and other threads) are captured automatically. Call `nk.flush()` before a short-lived process exits.

## Integrations

```python
# FastAPI / Starlette / any ASGI app: per-request scope, request id, error capture, re-raise
from nirikshan_sdk.integrations.asgi import NirikshanASGIMiddleware
app.add_middleware(NirikshanASGIMiddleware)

# logging: ERROR and above become events (with the traceback when logger.exception is used)
import logging
from nirikshan_sdk.integrations.logging import NirikshanHandler
logging.getLogger().addHandler(NirikshanHandler())

# asyncio: tasks whose exception nobody awaited ("Task exception was never retrieved")
nk.get_client().install_asyncio_handler(asyncio.get_running_loop())
```

## Behaviour you can rely on

| Concern | What it does |
| --- | --- |
| Never blocks your app | `capture_*` only puts an event on a bounded in-memory queue. A background thread does the network I/O, so an asyncio loop is never blocked. |
| Never crashes your app | Every SDK code path catches its own errors. A broken `before_send` drops the event, it does not raise. |
| Full queue | New events are dropped and counted (`client.transport.stats["dropped_full"]`) instead of growing memory. |
| Retries | Exponential backoff with jitter on connection errors, 408, 5xx. On 429/503 it waits for `Retry-After` (header, or `details.retry_after_seconds` in the body). |
| No pointless retries | Other 4xx (bad token, invalid payload) are dropped and counted, not retried. |
| Grouping | Each event has a `fingerprint` (exception type + in-app function names + file names). Line numbers and the message are left out so the same bug groups across deploys. |
| Privacy | Values under keys like `password`, `token`, `authorization`, `api_key`, `cookie` and query-string secrets in URLs are replaced with `[Filtered]` before sending. No local variables are sent. |
| Per-request isolation | Tags, user and breadcrumbs live in `contextvars`, so concurrent asyncio requests do not leak into each other (tested with 8 concurrent requests). |

## Options

`init(url, service, environment="production", release=None, ingest_token=None, sample_rate=1.0, before_send=None, max_breadcrumbs=50, max_queue=1000, batch_size=50, flush_interval=2.0, timeout=5.0, max_retries=4)`

## Tests

```bash
pip install -e sdk/python[dev]
cd sdk/python && pytest        # 23 tests against a real local HTTP server, including failure cases
pytest tests/e2e/test_sdk_ingest.py   # from the repo root: the SDK against the real Nirikshan API
```

## Limits (honest)

- Python only, no automatic framework patching beyond the ASGI/logging/asyncio hooks above.
- Stack frames carry file, function, line and the source line; no local variables, no source maps (that is a JavaScript concern).
- The server stores SDK events as log records with the details in `attributes`; there is no separate "issue" grouping view in the UI yet. The fingerprint is there so one can be built.
