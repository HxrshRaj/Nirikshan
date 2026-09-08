"""`nirikshan-api` -> uvicorn server."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "nirikshan.api.app:app",
        host=os.environ.get("NIRIKSHAN_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("NIRIKSHAN_API_PORT", "8000")),
        reload=os.environ.get("NIRIKSHAN_API_RELOAD", "") == "1",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
