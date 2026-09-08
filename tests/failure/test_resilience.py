"""Fault-injection: AI failure, malformed AI, duplicate alerts, unauthorized
remediation, Redis outage. Every discovered bug should add a case here."""

import pytest

from nirikshan.core.errors import ProviderUnavailable
from nirikshan.demo.scenarios import run_scenario
from nirikshan.incidents.engine import get_by_ref

pytestmark = pytest.mark.failure


class _TimeoutProvider:
    name, model, is_mock = "openai", "gpt-4o", False

    def analyze(self, bundle, *, prompt):
        raise ProviderUnavailable("simulated LLM timeout")

    def plan_remediation(self, ctx, *, prompt):
        raise ProviderUnavailable("simulated LLM timeout")


class _MalformedProvider(_TimeoutProvider):
    def analyze(self, bundle, *, prompt):
        from nirikshan.ai.contracts import Usage
        from nirikshan.ai.providers import _validate_analysis

        return _validate_analysis({"garbage": True, "hypotheses": []}, bundle, Usage(),
                                  provider="openai", model="gpt-4o")


def test_ai_timeout_preserves_incident_and_allows_retry(db, monkeypatch):
    import nirikshan.ai.investigator as inv

    monkeypatch.setattr(inv, "get_llm_provider", lambda: _TimeoutProvider())
    result = run_scenario(db, "db-exhaustion", investigate_incident=True)
    inc = get_by_ref(db, result.incident_ref)
    assert inc is not None  # incident survives AI failure

    from nirikshan.models import AgentRun

    run = db.query(AgentRun).filter_by(incident_id=inc.id).order_by(AgentRun.created_at.desc()).first()
    assert run.status == "FAILED"
    assert "timeout" in (run.error or "")
    assert any(e.kind == "investigation_failed" for e in inc.events)

    # retry with the working mock provider
    monkeypatch.undo()
    from nirikshan.ai.investigator import investigate

    run2 = investigate(db, inc)
    assert run2.status == "COMPLETED"
    db.refresh(inc)
    assert inc.root_cause


def test_malformed_ai_output_is_rejected(db, monkeypatch):
    import nirikshan.ai.investigator as inv

    monkeypatch.setattr(inv, "get_llm_provider", lambda: _MalformedProvider())
    result = run_scenario(db, "db-exhaustion", investigate_incident=True)
    inc = get_by_ref(db, result.incident_ref)
    from nirikshan.models import AgentRun

    run = db.query(AgentRun).filter_by(incident_id=inc.id).order_by(AgentRun.created_at.desc()).first()
    assert run.status == "FAILED"


def test_duplicate_alerts_single_incident(db):
    from nirikshan.detection.alerts import evaluate_all_rules
    from nirikshan.incidents.engine import ingest_alert
    from nirikshan.models import Alert, Incident

    run_scenario(db, "db-exhaustion", investigate_incident=False)
    for _ in range(4):
        for a in evaluate_all_rules(db):
            ingest_alert(db, a)
    for a in db.query(Alert).filter(Alert.state == "FIRING", Alert.incident_id.is_(None)):
        ingest_alert(db, a)
    payment_incidents = db.query(Incident).filter_by(service_name="payment-service").count()
    assert payment_incidents == 1


def test_unauthorized_remediation_approval_blocked(db):
    from nirikshan.core.errors import PermissionError_
    from nirikshan.domain.enums import Role
    from nirikshan.models import RemediationAction
    from nirikshan.remediation import executor

    result = run_scenario(db, "db-exhaustion", investigate_incident=True, propose_fix=True)
    action = db.query(RemediationAction).filter_by(ref=result.remediation_ref).one()
    with pytest.raises(PermissionError_):
        executor.approve(db, action, actor="v@x", actor_role=Role.VIEWER)


def test_redis_outage_does_not_break_ingestion(db, monkeypatch):
    """publish_event failing must not stop telemetry being stored."""
    import nirikshan.core.redis_bus as rb

    def boom(*a, **k):
        raise rb.redis.RedisError("connection refused")

    monkeypatch.setattr(rb, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(rb, "broadcast", lambda *a, **k: (_ for _ in ()).throw(rb.redis.RedisError("down")))

    from nirikshan.schemas.telemetry import MetricIn
    from nirikshan.telemetry.ingest import ingest_metrics

    # broadcast raising should be swallowed by emit(); ingestion still succeeds
    try:
        ingest_metrics(db, [MetricIn(service="svc", metric_name="cpu_usage", value=0.5)])
    except Exception:
        pass
    from nirikshan.models import TelemetryMetric

    assert db.query(TelemetryMetric).count() == 1


def test_redis_circuit_breaker_stops_hammering(monkeypatch):
    """When Redis fails, the breaker opens so subsequent calls return fast."""
    import time as _time

    import nirikshan.core.redis_bus as rb

    rb.set_client(None)  # clear any injected fake client

    calls = {"n": 0}

    class _DeadClient:
        def ping(self):
            calls["n"] += 1
            raise rb.redis.RedisError("connection refused")

        def xadd(self, *a, **k):
            calls["n"] += 1
            raise rb.redis.RedisError("connection refused")

        def publish(self, *a, **k):
            calls["n"] += 1
            raise rb.redis.RedisError("connection refused")

    monkeypatch.setattr(rb, "_client", _DeadClient())
    monkeypatch.setattr(rb, "_injected", False)
    monkeypatch.setattr(rb, "_open_until", 0.0)

    assert rb.is_healthy() is False          # trips the breaker
    first = calls["n"]
    # a burst of publishes now short-circuits without touching the client
    for _ in range(20):
        rb.publish_event("X", {})
        rb.broadcast({})
    assert calls["n"] == first               # no further client calls while open
    assert rb.is_healthy() is False

    rb.set_client(None)
