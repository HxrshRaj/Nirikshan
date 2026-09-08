from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from nirikshan.domain.enums import LogLevel, SpanStatus


class LogIn(BaseModel):
    timestamp: datetime | None = None
    service: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="production", max_length=80)
    level: LogLevel = LogLevel.INFO
    message: str = Field(min_length=1, max_length=8000)
    trace_id: str | None = Field(default=None, max_length=64)
    span_id: str | None = Field(default=None, max_length=32)
    request_id: str | None = Field(default=None, max_length=64)
    host: str | None = Field(default=None, max_length=200)
    deployment_id: str | None = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("log message must not be blank")
        return v


class MetricIn(BaseModel):
    timestamp: datetime | None = None
    service: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="production", max_length=80)
    metric_name: str = Field(min_length=1, max_length=80)
    value: float
    unit: str = Field(default="", max_length=24)
    labels: dict = Field(default_factory=dict)

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("metric value must be finite")
        return v


class SpanIn(BaseModel):
    span_id: str = Field(min_length=1, max_length=32)
    parent_span_id: str | None = Field(default=None, max_length=32)
    service: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=200)
    start_time: datetime | None = None
    duration_ms: float = Field(ge=0)
    status: SpanStatus = SpanStatus.OK
    attributes: dict = Field(default_factory=dict)


class TraceIn(BaseModel):
    trace_id: str = Field(min_length=1, max_length=64)
    environment: str = Field(default="production", max_length=80)
    spans: list[SpanIn] = Field(min_length=1, max_length=500)


class LogBatch(BaseModel):
    logs: list[LogIn] = Field(min_length=1, max_length=1000)


class MetricBatch(BaseModel):
    metrics: list[MetricIn] = Field(min_length=1, max_length=2000)


class TraceBatch(BaseModel):
    traces: list[TraceIn] = Field(min_length=1, max_length=200)


class IngestResult(BaseModel):
    accepted: int
    rejected: int
    errors: list[str] = Field(default_factory=list)


class LogOut(BaseModel):
    id: str
    ts: datetime
    service: str
    environment_id: str
    level: str
    message: str
    trace_id: str | None
    span_id: str | None
    request_id: str | None
    host: str | None
    attributes: dict


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class MetricSeries(BaseModel):
    service: str
    metric_name: str
    unit: str
    points: list[MetricPoint]
    aggregation: str


class SpanOut(BaseModel):
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    started_at: datetime
    duration_ms: float
    status: str
    attributes: dict


class TraceOut(BaseModel):
    trace_id: str
    root_operation: str
    started_at: datetime
    duration_ms: float
    span_count: int
    error_count: int
    status: str
    spans: list[SpanOut]
