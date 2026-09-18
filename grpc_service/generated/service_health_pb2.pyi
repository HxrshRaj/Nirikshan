from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HealthStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEALTH_STATUS_UNSPECIFIED: _ClassVar[HealthStatus]
    HEALTHY: _ClassVar[HealthStatus]
    DEGRADED: _ClassVar[HealthStatus]
    UNHEALTHY: _ClassVar[HealthStatus]
    UNKNOWN: _ClassVar[HealthStatus]
HEALTH_STATUS_UNSPECIFIED: HealthStatus
HEALTHY: HealthStatus
DEGRADED: HealthStatus
UNHEALTHY: HealthStatus
UNKNOWN: HealthStatus

class ServiceHealthRequest(_message.Message):
    __slots__ = ("service_name", "environment", "window_seconds", "poll_interval_seconds")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    ENVIRONMENT_FIELD_NUMBER: _ClassVar[int]
    WINDOW_SECONDS_FIELD_NUMBER: _ClassVar[int]
    POLL_INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    environment: str
    window_seconds: int
    poll_interval_seconds: int
    def __init__(self, service_name: _Optional[str] = ..., environment: _Optional[str] = ..., window_seconds: _Optional[int] = ..., poll_interval_seconds: _Optional[int] = ...) -> None: ...

class ServiceHealthUpdate(_message.Message):
    __slots__ = ("service_name", "tier", "status", "window_seconds", "latency_p95_ms", "latency_avg_ms", "error_rate", "request_rate_per_min", "log_error_count", "cpu_usage", "memory_usage", "db_connections", "queue_depth", "reasons", "computed_at_unix_ms")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    WINDOW_SECONDS_FIELD_NUMBER: _ClassVar[int]
    LATENCY_P95_MS_FIELD_NUMBER: _ClassVar[int]
    LATENCY_AVG_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_RATE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_RATE_PER_MIN_FIELD_NUMBER: _ClassVar[int]
    LOG_ERROR_COUNT_FIELD_NUMBER: _ClassVar[int]
    CPU_USAGE_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USAGE_FIELD_NUMBER: _ClassVar[int]
    DB_CONNECTIONS_FIELD_NUMBER: _ClassVar[int]
    QUEUE_DEPTH_FIELD_NUMBER: _ClassVar[int]
    REASONS_FIELD_NUMBER: _ClassVar[int]
    COMPUTED_AT_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    tier: int
    status: HealthStatus
    window_seconds: int
    latency_p95_ms: float
    latency_avg_ms: float
    error_rate: float
    request_rate_per_min: float
    log_error_count: int
    cpu_usage: float
    memory_usage: float
    db_connections: float
    queue_depth: float
    reasons: _containers.RepeatedScalarFieldContainer[str]
    computed_at_unix_ms: int
    def __init__(self, service_name: _Optional[str] = ..., tier: _Optional[int] = ..., status: _Optional[_Union[HealthStatus, str]] = ..., window_seconds: _Optional[int] = ..., latency_p95_ms: _Optional[float] = ..., latency_avg_ms: _Optional[float] = ..., error_rate: _Optional[float] = ..., request_rate_per_min: _Optional[float] = ..., log_error_count: _Optional[int] = ..., cpu_usage: _Optional[float] = ..., memory_usage: _Optional[float] = ..., db_connections: _Optional[float] = ..., queue_depth: _Optional[float] = ..., reasons: _Optional[_Iterable[str]] = ..., computed_at_unix_ms: _Optional[int] = ...) -> None: ...
