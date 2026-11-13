"""StageOutcome invariants: spec 01 value object and spec 06d review contract."""

import dataclasses

import pytest

from ai_factory.domain.errors import InvalidStageOutcomeError
from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from ai_factory.domain.outcomes import ReviewFeedback, StageOutcome


def _finding(severity: FindingSeverity, message: str) -> Finding:
    return Finding(
        severity=severity,
        category=FindingCategory.TESTS,
        location="tests/test_outcomes.py:1",
        message=message,
        status=FindingStatus.UNVERIFIED,
    )


def test_spec01_ac2_outcome_keeps_values_and_defaults_findings() -> None:
    """AC2: findings default to an empty tuple and provided values are kept."""
    outcome = StageOutcome(summary="Looks good")
    assert outcome.summary == "Looks good"
    assert outcome.findings == ()
    assert outcome.omitted_findings == 0
    assert outcome.approved is True


@pytest.mark.parametrize("summary", ["", "   "])
def test_spec01_ac2_blank_summary_is_rejected(summary: str) -> None:
    """AC2: a blank summary raises InvalidStageOutcomeError."""
    with pytest.raises(InvalidStageOutcomeError):
        StageOutcome(summary=summary)


def test_spec01_ac2_outcome_is_immutable() -> None:
    """AC2: StageOutcome instances are frozen."""
    outcome = StageOutcome(summary="Looks good")
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.approved = False


@pytest.mark.parametrize(
    ("severity", "approved"),
    [
        (FindingSeverity.BLOCKER, False),
        (FindingSeverity.MAJOR, False),
        (FindingSeverity.MINOR, True),
    ],
)
def test_spec06d_ac2_spec07_ac10_approval_is_derived_from_severity(
    severity: FindingSeverity, approved: bool
) -> None:
    """AC2/AC10: the verdict is derived from the findings, never read from the model."""
    outcome = StageOutcome(summary="verdict", findings=(_finding(severity, "issue"),))
    assert outcome.approved is approved


def test_spec06d_ac2_outcome_does_not_accept_an_approved_argument() -> None:
    """AC2: approval cannot be passed in any more."""
    with pytest.raises(TypeError):
        StageOutcome(approved=True, summary="Looks good")


def test_spec06d_ac3_findings_are_sorted_by_severity() -> None:
    """AC3: blockers first, then majors, then minors."""
    outcome = StageOutcome(
        summary="verdict",
        findings=(
            _finding(FindingSeverity.MINOR, "minor"),
            _finding(FindingSeverity.BLOCKER, "blocker"),
            _finding(FindingSeverity.MAJOR, "major"),
        ),
    )
    assert [finding.severity for finding in outcome.findings] == [
        FindingSeverity.BLOCKER,
        FindingSeverity.MAJOR,
        FindingSeverity.MINOR,
    ]


def test_spec06d_ac3_findings_are_capped_at_twenty() -> None:
    """AC3: the twentieth-first minor is counted, not carried."""
    minors = tuple(_finding(FindingSeverity.MINOR, f"minor {index}") for index in range(21))
    outcome = StageOutcome(summary="verdict", findings=minors)
    assert len(outcome.findings) == 20
    assert outcome.omitted_findings == 1
    assert outcome.findings[0].message == "minor 0"


@pytest.mark.parametrize(("count", "omitted"), [(22, 2), (40, 20)])
def test_spec06d_ac3_omitted_findings_counts_every_dropped_finding(
    count: int, omitted: int
) -> None:
    """AC3: every dropped finding is counted, not just the surplus over the cap."""
    minors = tuple(_finding(FindingSeverity.MINOR, f"minor {index}") for index in range(count))
    outcome = StageOutcome(summary="verdict", findings=minors)
    assert len(outcome.findings) == 20
    assert outcome.omitted_findings == omitted


def test_spec06d_ac9_empty_feedback_omits_nothing() -> None:
    """AC9: the no-feedback value reports zero omitted findings."""
    assert ReviewFeedback().omitted_findings == 0


def test_spec06d_ac3_blockers_are_kept_before_minors() -> None:
    """AC3: the cap never drops a blocker while it keeps minors."""
    findings = (
        *(_finding(FindingSeverity.MINOR, f"minor {index}") for index in range(20)),
        _finding(FindingSeverity.BLOCKER, "blocker"),
    )
    outcome = StageOutcome(summary="verdict", findings=findings)
    assert len(outcome.findings) == 20
    assert outcome.omitted_findings == 1
    assert outcome.findings[0].severity is FindingSeverity.BLOCKER
    assert outcome.approved is False
