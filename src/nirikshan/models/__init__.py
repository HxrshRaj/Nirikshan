"""ORM model registry.

Importing this package is sufficient to populate ``Base.metadata`` with every
table (used by ``create_all`` and Alembic autogenerate).
"""

from __future__ import annotations

from nirikshan.models.agents import AgentRun, AgentToolCall, LLMCall, PromptVersion
from nirikshan.models.alerting import Alert, AlertRule, Anomaly, MetricBaseline
from nirikshan.models.audit import AuditLog
from nirikshan.models.auth import User
from nirikshan.models.base import Base
from nirikshan.models.deployments import Deployment
from nirikshan.models.incidents import (
    Incident,
    IncidentEvent,
    IncidentEvidence,
    IncidentHypothesis,
)
from nirikshan.models.knowledge import HistoricalIncident
from nirikshan.models.org import (
    Environment,
    Organization,
    Service,
    ServiceDependency,
    ServiceInstance,
)
from nirikshan.models.remediation import (
    RemediationAction,
    RemediationApproval,
    RemediationExecution,
)
from nirikshan.models.telemetry import TelemetryLog, TelemetryMetric, Trace, TraceSpan

__all__ = [
    "AgentRun",
    "AgentToolCall",
    "Alert",
    "AlertRule",
    "Anomaly",
    "AuditLog",
    "Base",
    "Deployment",
    "Environment",
    "HistoricalIncident",
    "Incident",
    "IncidentEvent",
    "IncidentEvidence",
    "IncidentHypothesis",
    "LLMCall",
    "MetricBaseline",
    "Organization",
    "PromptVersion",
    "RemediationAction",
    "RemediationApproval",
    "RemediationExecution",
    "Service",
    "ServiceDependency",
    "ServiceInstance",
    "TelemetryLog",
    "TelemetryMetric",
    "Trace",
    "TraceSpan",
    "User",
]
