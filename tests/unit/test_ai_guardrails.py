import pytest

from nirikshan.ai import mock_reasoner
from nirikshan.ai.contracts import Usage
from nirikshan.ai.providers import _validate_analysis, _validate_plan
from nirikshan.core.errors import ProviderUnavailable

pytestmark = pytest.mark.unit


def _bundle(**over):
    b = {
        "incident": {"ref": "INC-1", "service": "payment-service", "detected_at": "2026-01-01T00:00:00Z"},
        "metrics": [
            {"metric": "database_connections", "current": 99, "baseline_mean": 34, "baseline_std": 4,
             "zscore": 16, "anomaly": True, "baseline_p95": 40},
            {"metric": "request_latency_ms", "current": 900, "baseline_mean": 150, "baseline_std": 20,
             "zscore": 30, "anomaly": True, "baseline_p95": 190},
        ],
        "anomalies": [
            {"metric": "database_connections", "score": 16, "direction": "high", "observed_value": 99,
             "expected_high": 40, "confidence": 0.9},
            {"metric": "request_latency_ms", "score": 30, "direction": "high", "observed_value": 900,
             "expected_high": 190, "confidence": 0.9},
        ],
        "logs": {"error_count": 40, "fatal_count": 0,
                 "top_patterns": ["timeout acquiring"], "top_patterns_text": "timeout acquiring"},
        "deployments": [],
        "dependencies": {"unhealthy_dependencies": []},
        "prior_incidents": [],
    }
    b.update(over)
    return b


def test_mock_reasoner_identifies_db_saturation():
    result = mock_reasoner.analyze(_bundle())
    assert result.is_mock
    assert result.hypotheses[0].category == "database_saturation"
    assert result.confidence >= 0.7
    # every grounded id must reference something in the bundle
    for h in result.hypotheses:
        for e in h.supporting_evidence_ids:
            assert e.split(":")[0] in {"metric", "logs", "deploy", "dep", "prior", "anomaly"}


def test_mock_reasoner_deployment_regression():
    b = _bundle(
        deployments=[{"ref": "DEP-9", "version": "v2", "previous_version": "v1",
                      "minutes_before_incident": 5, "change_summary": "x"}],
        metrics=[{"metric": "error_rate", "current": 0.1, "baseline_mean": 0.01, "baseline_std": 0.005,
                  "zscore": 18, "anomaly": True, "baseline_p95": 0.02}],
        anomalies=[{"metric": "error_rate", "score": 18, "direction": "high", "observed_value": 0.1,
                    "expected_high": 0.02, "confidence": 0.9}],
        logs={"error_count": 60, "fatal_count": 0, "top_patterns": [], "top_patterns_text": ""},
    )
    result = mock_reasoner.analyze(b)
    assert result.hypotheses[0].category == "deployment_regression"


def test_mock_reasoner_inconclusive_when_no_signal():
    b = _bundle(metrics=[], anomalies=[], logs={"error_count": 0, "fatal_count": 0,
                                                "top_patterns": [], "top_patterns_text": ""})
    result = mock_reasoner.analyze(b)
    assert result.hypotheses[0].category == "inconclusive"
    assert result.confidence < 0.5


def test_validate_analysis_drops_uncited_evidence():
    raw = {
        "root_cause": "db", "confidence": 0.9, "summary": "s",
        "hypotheses": [{"title": "db", "category": "database_saturation", "rationale": "r",
                        "confidence": 0.9,
                        "supporting_evidence_ids": ["metric:database_connections", "metric:made_up"]}],
        "contributing_factors": [], "recommended_actions": [],
    }
    result = _validate_analysis(raw, _bundle(), Usage(), provider="openai", model="gpt-4o")
    assert "metric:database_connections" in result.hypotheses[0].supporting_evidence_ids
    assert "metric:made_up" not in result.hypotheses[0].supporting_evidence_ids
    assert any("uncited" in w for w in result.warnings)


def test_validate_plan_rejects_disallowed_action():
    with pytest.raises(ProviderUnavailable):
        _validate_plan({"action_name": "delete_database", "parameters": {}}, {"service": "x"},
                       Usage(), provider="openai", model="gpt-4o")
