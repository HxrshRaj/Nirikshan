"""Shared enumerations used by ORM models, API schemas and business logic."""

from __future__ import annotations

from enum import StrEnum


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"

    @property
    def rank(self) -> int:
        return {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}[self.value]


class SpanStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    UNSET = "UNSET"


class ServiceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class DeploymentStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class AlertState(StrEnum):
    FIRING = "FIRING"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class AlertSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComparisonOp(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"


class AlertSignalKind(StrEnum):
    METRIC = "metric"
    ERROR_RATE = "error_rate"
    LATENCY = "latency"
    LOG_MATCH = "log_match"
    SERVICE_HEALTH = "service_health"
    RESOURCE = "resource"


class IncidentStatus(StrEnum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# Allowed forward transitions for the incident state machine.
INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.MITIGATING,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.ACKNOWLEDGED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.MITIGATING,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.MITIGATING: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED, IncidentStatus.INVESTIGATING},
    IncidentStatus.CLOSED: set(),
}

OPEN_INCIDENT_STATUSES = {
    IncidentStatus.DETECTED,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.ACKNOWLEDGED,
    IncidentStatus.MITIGATING,
}


class Severity(StrEnum):
    SEV1 = "SEV-1"
    SEV2 = "SEV-2"
    SEV3 = "SEV-3"
    SEV4 = "SEV-4"

    @property
    def rank(self) -> int:
        return {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3, "SEV-4": 4}[self.value]


class AnomalyMethod(StrEnum):
    ZSCORE = "zscore"
    EWMA = "ewma"
    ROLLING_IQR = "rolling_iqr"
    ISOLATION_FOREST = "isolation_forest"


class AgentKind(StrEnum):
    INVESTIGATOR = "investigator"
    REMEDIATION = "remediation"


class AgentRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RemediationMode(StrEnum):
    OBSERVE = "OBSERVE"
    RECOMMEND = "RECOMMEND"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    AUTONOMOUS = "AUTONOMOUS"


class RemediationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    VERIFYING = "VERIFYING"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Role(StrEnum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER"
    INCIDENT_COMMANDER = "INCIDENT_COMMANDER"
    ADMIN = "ADMIN"

    @property
    def rank(self) -> int:
        return {
            "VIEWER": 0,
            "ENGINEER": 1,
            "INCIDENT_COMMANDER": 2,
            "ADMIN": 3,
        }[self.value]


class EvidenceKind(StrEnum):
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    DEPLOYMENT = "deployment"
    ALERT = "alert"
    DEPENDENCY = "dependency"
    ANOMALY = "anomaly"
    PRIOR_INCIDENT = "prior_incident"
    SERVICE_HEALTH = "service_health"
