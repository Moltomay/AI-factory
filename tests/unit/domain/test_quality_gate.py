"""AC3: quality gate combines deterministic checks and the QA review."""

from ai_factory.domain.outcomes import StageOutcome
from ai_factory.domain.quality_gate import CHECKS_FAILED_FINDING, combine_quality_results


def test_spec01_ac3_checks_and_review_both_pass() -> None:
    """AC3: with checks passing, the review outcome is returned unchanged."""
    review = StageOutcome(approved=True, summary="QA review passed", findings=("minor nit",))
    result = combine_quality_results(checks_passed=True, review_outcome=review)
    assert result.approved is True
    assert result.summary == "QA review passed"
    assert result.findings == ("minor nit",)


def test_spec01_ac3_failed_checks_force_rejection_and_add_finding() -> None:
    """AC3: failing checks reject even an approving review and add a finding."""
    review = StageOutcome(approved=True, summary="QA review passed", findings=("minor nit",))
    result = combine_quality_results(checks_passed=False, review_outcome=review)
    assert result.approved is False
    assert result.findings == (CHECKS_FAILED_FINDING, "minor nit")


def test_spec01_ac3_review_rejection_is_preserved_when_checks_pass() -> None:
    """AC3: a passing checks run does not override a rejecting review."""
    review = StageOutcome(approved=False, summary="Missing tests")
    result = combine_quality_results(checks_passed=True, review_outcome=review)
    assert result.approved is False
    assert result.summary == "Missing tests"
    assert result.findings == ()
