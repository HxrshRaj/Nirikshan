"""Application factory + lifespan + global error handling."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nirikshan.core.config import get_settings
from nirikshan.core.db import create_all, init_engine
from nirikshan.core.errors import ErrorEnvelope, NirikshanError
from nirikshan.core.logging import configure_logging, get_logger
from nirikshan.core.redis_bus import ensure_group, is_healthy

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)
    create_all()  # dev/test bootstrap; production also runs `alembic upgrade head`

    from nirikshan.ai.prompts import sync_prompts
    from nirikshan.core.db import session_scope
    from nirikshan.security.users import ensure_bootstrap_admin

    with session_scope() as db:
        added = sync_prompts(db)
        admin = ensure_bootstrap_admin(db)
    try:
        ensure_group()
    except Exception as exc:
        log.warning("api.redis_group_failed", error=str(exc))
    log.info(
        "api.started",
        env=settings.env,
        llm_provider=settings.llm_effective_provider,
        prompts_synced=added,
        bootstrap_admin=bool(admin),
        redis=is_healthy(),
    )
    yield
    log.info("api.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Nirikshan API",
        version="0.1.0",
        description="AI-Powered SRE & Incident Response Platform",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except NirikshanError as exc:  # pragma: no cover - handled below normally
            raise exc
        response.headers["x-request-id"] = rid
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
        return response

    _install_error_handlers(app)
    _mount_routers(app)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"name": "Nirikshan", "service": "api", "docs": "/docs"}

    return app


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NirikshanError)
    async def _domain(request: Request, exc: NirikshanError):
        if exc.status_code >= 500:
            log.warning("api.domain_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorEnvelope(code=exc.code, message=exc.message, details=exc.details).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=ErrorEnvelope(
                code="validation_error",
                message="request validation failed",
                details={"errors": exc.errors()},
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("api.unhandled", error=str(exc), path=str(request.url.path), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=ErrorEnvelope(code="internal_error", message="internal server error").model_dump(),
        )


def _mount_routers(app: FastAPI) -> None:
    from nirikshan.api.routers import (
        agents,
        alerting,
        auth,
        catalog,
        demo,
        deployments,
        incidents,
        observability,
        remediations,
        telemetry,
    )

    for module in (
        auth,
        telemetry,
        catalog,
        deployments,
        alerting,
        incidents,
        remediations,
        agents,
        observability,
        demo,
    ):
        app.include_router(module.router, prefix="/api")


app = create_app()
