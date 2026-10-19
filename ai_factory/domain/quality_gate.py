"""Business rule combining the deterministic checks and the QA agent review."""

from ai_factory.domain.outcomes import StageOutcome

CHECKS_FAILED_FINDING = "Deterministic checks (lint/tests) failed."


def combine_quality_results(checks_passed: bool, review_outcome: StageOutcome) -> StageOutcome:
    """Combine automated checks with the QA agent review into one QA verdict.

    Args:
        checks_passed: Whether the deterministic checks (lint/tests) passed.
        review_outcome: The QA agent's review of the change.

    Returns:
        The combined QA outcome: approved only when both inputs approve. When
        the checks failed, their synthetic finding is prepended to the review
        findings so the retry feedback mentions them.
    """
    if checks_passed:
        return review_outcome
    return StageOutcome(
        approved=False,
        summary=review_outcome.summary,
        findings=(CHECKS_FAILED_FINDING, *review_outcome.findings),
    )
