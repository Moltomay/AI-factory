"""Spec 06d AC1: the Finding value object shared by both reviewer agents."""

import dataclasses

import pytest

from ai_factory.domain.errors import InvalidFindingError
from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)


def _verified_finding() -> Finding:
    return Finding(
        severity=FindingSeverity.BLOCKER,
        category=FindingCategory.TESTS,
        location="tests/test_parser.py:42",
        message="The assertion holds for any implementation.",
        status=FindingStatus.VERIFIED,
        evidence="- assert result is not None",
    )


@pytest.mark.parametrize("location", ["", "   "])
def test_spec06d_ac1_blank_location_is_rejected(location: str) -> None:
    """AC1: a finding must point somewhere."""
    with pytest.raises(InvalidFindingError):
        dataclasses.replace(_verified_finding(), location=location)


@pytest.mark.parametrize("message", ["", "   "])
def test_spec06d_ac1_blank_message_is_rejected(message: str) -> None:
    """AC1: a finding must say what is wrong."""
    with pytest.raises(InvalidFindingError):
        dataclasses.replace(_verified_finding(), message=message)


def test_spec06d_ac1_unknown_severity_is_rejected() -> None:
    """AC1: the severity vocabulary is closed."""
    with pytest.raises(InvalidFindingError):
        dataclasses.replace(_verified_finding(), severity="critical")


def test_spec06d_ac1_unknown_status_is_rejected() -> None:
    """AC1: the status vocabulary is closed."""
    with pytest.raises(InvalidFindingError):
        dataclasses.replace(_verified_finding(), status="maybe")


@pytest.mark.parametrize("evidence", ["", "   "])
def test_spec06d_ac1_verified_finding_requires_evidence(evidence: str) -> None:
    """AC1: a verified finding without proof is invalid."""
    with pytest.raises(InvalidFindingError):
        dataclasses.replace(_verified_finding(), evidence=evidence)


def test_spec06d_ac1_unverified_finding_accepts_empty_evidence() -> None:
    """AC1: an explicit unverified finding may carry no evidence."""
    finding = dataclasses.replace(_verified_finding(), status=FindingStatus.UNVERIFIED, evidence="")
    assert finding.status is FindingStatus.UNVERIFIED
    assert finding.evidence == ""


def test_spec06d_ac1_blank_ac_becomes_none() -> None:
    """AC1: an empty AC reference means "no AC", not an empty string."""
    assert dataclasses.replace(_verified_finding(), ac="   ").ac is None


@pytest.mark.parametrize(
    ("severity", "blocking"),
    [
        (FindingSeverity.BLOCKER, True),
        (FindingSeverity.MAJOR, True),
        (FindingSeverity.MINOR, False),
    ],
)
def test_spec06d_ac2_blocking_severities(severity: FindingSeverity, blocking: bool) -> None:
    """AC2: only blocker and major findings block."""
    assert dataclasses.replace(_verified_finding(), severity=severity).is_blocking is blocking
