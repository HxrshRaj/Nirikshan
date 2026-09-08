from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from nirikshan.api.deps import current_user, get_db, rate_limit
from nirikshan.models import User
from nirikshan.schemas.common import Page
from nirikshan.schemas.telemetry import (
    IngestResult,
    LogBatch,
    LogIn,
    LogOut,
    MetricBatch,
    MetricIn,
    MetricSeries,
    TraceBatch,
    TraceIn,
    TraceOut,
)
from nirikshan.telemetry import ingest, query

router = APIRouter(tags=["telemetry"])

_ingest_rl = Depends(rate_limit("telemetry"))


@router.post("/telemetry/logs", response_model=IngestResult, dependencies=[_ingest_rl])
def ingest_logs(body: LogBatch | LogIn, db: Session = Depends(get_db)) -> IngestResult:
    items = body.logs if isinstance(body, LogBatch) else [body]
    return ingest.ingest_logs(db, items)


@router.post("/telemetry/metrics", response_model=IngestResult, dependencies=[_ingest_rl])
def ingest_metrics(body: MetricBatch | MetricIn, db: Session = Depends(get_db)) -> IngestResult:
    items = body.metrics if isinstance(body, MetricBatch) else [body]
    return ingest.ingest_metrics(db, items)


@router.post("/telemetry/traces", response_model=IngestResult, dependencies=[_ingest_rl])
def ingest_traces(body: TraceBatch | TraceIn, db: Session = Depends(get_db)) -> IngestResult:
    items = body.traces if isinstance(body, TraceBatch) else [body]
    return ingest.ingest_traces(db, items)


@router.get("/logs", response_model=Page[LogOut])
def search_logs(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    environment: str = "production",
    service: str | None = None,
    level: str | None = None,
    min_level: str | None = None,
    q: str | None = Query(default=None, alias="query"),
    trace_id: str | None = None,
    request_id: str | None = None,
    minutes: int = Query(default=60, ge=1, le=20160),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> Page[LogOut]:
    rows, total = query.search_logs(
        db, environment=environment, service=service, level=level, min_level=min_level,
        query=q, trace_id=trace_id, request_id=request_id, minutes=minutes, limit=limit, offset=offset,
    )
    return Page[LogOut](items=rows, total=total, limit=limit, offset=offset)


@router.get("/logs/histogram")
def logs_histogram(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    environment: str = "production",
    service: str | None = None,
    minutes: int = Query(default=60, ge=5, le=1440),
    buckets: int = Query(default=60, ge=10, le=200),
) -> list[dict]:
    return query.log_histogram(db, environment=environment, service=service, minutes=minutes, buckets=buckets)


@router.get("/metrics/series", response_model=MetricSeries)
def metric_series(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    service: str = Query(...),
    metric: str = Query(...),
    environment: str = "production",
    minutes: int = Query(default=60, ge=5, le=20160),
    step_seconds: int = Query(default=60, ge=15, le=3600),
    aggregation: str = Query(default="avg"),
) -> MetricSeries:
    return query.metric_series(
        db, service=service, metric_name=metric, environment=environment,
        minutes=minutes, step_seconds=step_seconds, aggregation=aggregation,
    )


@router.get("/metrics/names")
def metric_names(
    db: Session = Depends(get_db), _u: User = Depends(current_user), service: str | None = None
) -> list[str]:
    return query.list_metric_names(db, service=service)


@router.get("/traces")
def list_traces(
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
    environment: str = "production",
    service: str | None = None,
    only_errors: bool = False,
    minutes: int = Query(default=60, ge=5, le=1440),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    return query.list_traces(
        db, environment=environment, service=service, only_errors=only_errors, minutes=minutes, limit=limit
    )


@router.get("/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> TraceOut:
    return query.get_trace(db, trace_id)
