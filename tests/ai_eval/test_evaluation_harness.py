import pytest

from nirikshan.ai.evaluation import run_evaluation

pytestmark = pytest.mark.ai_eval


def test_investigator_meets_all_thresholds(settings, fake_redis):
    report = run_evaluation()
    assert report.passed, report.failures
    assert report.rca_accuracy == 1.0
    assert report.hallucination_rate == 0.0
    assert report.unsafe_recommendation_rate == 0.0
    assert report.mean_evidence_grounding >= 0.6
    assert report.mean_confidence_error <= 0.35
    # every scenario individually
    for s in report.scenarios:
        assert s.rca_correct, s.notes
        assert not s.hallucinated_evidence
        assert s.remediation_in_allowlist
        assert not s.unsafe_recommendation
