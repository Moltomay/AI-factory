"""AC2: StageOutcome value object invariants."""

import dataclasses

import pytest

from ai_factory.domain.errors import InvalidStageOutcomeError
from ai_factory.domain.outcomes import StageOutcome


def test_spec01_ac2_outcome_keeps_values_and_defaults_findings() -> None:
    """AC2: findings default to an empty tuple and provided values are kept."""
    outcome = StageOutcome(approved=True, summary="Looks good")
    assert outcome.approved is True
    assert outcome.summary == "Looks good"
    assert outcome.findings == ()


@pytest.mark.parametrize("summary", ["", "   "])
def test_spec01_ac2_blank_summary_is_rejected(summary: str) -> None:
    """AC2: a blank summary raises InvalidStageOutcomeError."""
    with pytest.raises(InvalidStageOutcomeError):
        StageOutcome(approved=False, summary=summary)


def test_spec01_ac2_outcome_is_immutable() -> None:
    """AC2: StageOutcome instances are frozen."""
    outcome = StageOutcome(approved=True, summary="Looks good")
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.approved = False
