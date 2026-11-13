"""Spec 06d AC4: the deterministic gate builds a blocking outcome by itself."""

from ai_factory.domain.findings import FindingCategory, FindingSeverity, FindingStatus
from ai_factory.domain.quality_gate import (
    DETERMINISTIC_FAILURE_LOCATION,
    failed_checks_outcome,
)


def test_spec06d_ac4_spec07_ac10_failed_checks_outcome_is_a_verified_blocker() -> None:
    """AC4/AC10: a red check yields one actionable blocker, without an agent review."""
    outcome = failed_checks_outcome()

    assert outcome.approved is False
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.severity is FindingSeverity.BLOCKER
    assert finding.status is FindingStatus.VERIFIED
    assert finding.category is FindingCategory.OTHER
    assert finding.location == DETERMINISTIC_FAILURE_LOCATION
    assert "checks" in finding.message.lower()
    assert finding.evidence
