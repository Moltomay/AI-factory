"""Business rule turning a red deterministic gate into a blocking stage outcome.

The QA agent is not consulted when the gate is red (spec 06d): this outcome is
the whole verdict, so the pipeline still gets an actionable finding without
paying for a review of a broken build.
"""

from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from ai_factory.domain.outcomes import StageOutcome

CHECKS_FAILED_FINDING = "Deterministic checks (lint/tests) failed."
DETERMINISTIC_FAILURE_LOCATION = "deterministic-checks"
DETERMINISTIC_FAILURE_EVIDENCE = "the quality runner reported a failing check"


def failed_checks_outcome() -> StageOutcome:
    """Build the verdict of a red deterministic gate.

    Returns:
        A non-approved outcome carrying one verified blocker.
    """
    return StageOutcome(
        summary=CHECKS_FAILED_FINDING,
        findings=(
            Finding(
                severity=FindingSeverity.BLOCKER,
                category=FindingCategory.OTHER,
                location=DETERMINISTIC_FAILURE_LOCATION,
                message=CHECKS_FAILED_FINDING,
                status=FindingStatus.VERIFIED,
                evidence=DETERMINISTIC_FAILURE_EVIDENCE,
            ),
        ),
    )
