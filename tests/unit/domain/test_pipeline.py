"""AC4-AC8: pipeline state machine, retry budget and role mapping."""

import pytest

from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.pipeline import (
    FAILED_REASON_TEMPLATE,
    MAX_DEVELOPMENT_ATTEMPTS,
    AgentRole,
    PipelineRun,
    PipelineStage,
)
from ai_factory.domain.ticket import Ticket


def _make_run() -> PipelineRun:
    return PipelineRun(ticket=Ticket(ticket_id="card-1", title="Do the thing", description=""))


def _advance_to_pull_request_opened(run: PipelineRun) -> None:
    run.start()
    run.development_completed()
    run.record_review_outcome(approved=True)


def test_spec01_ac4_happy_path_reaches_pull_request_opened() -> None:
    """AC4: a fully approved run ends with the PR opened and one attempt."""
    run = _make_run()
    assert run.stage is PipelineStage.NEW
    assert not run.is_finished
    run.start()
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 1
    run.development_completed()
    assert run.stage is PipelineStage.REVIEW
    run.record_review_outcome(approved=True)
    assert run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert run.is_finished
    assert run.failure_reason is None


def test_spec01_ac5_review_rejection_sends_back_to_implementing() -> None:
    """AC5: a review rejection starts a new development attempt."""
    run = _make_run()
    run.start()
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 2


def test_spec01_ac5_second_review_rejection_starts_another_attempt() -> None:
    """AC5: every rejection before the budget starts a fresh attempt."""
    run = _make_run()
    run.start()
    run.development_completed()
    run.record_review_outcome(approved=False)
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 3


def test_spec01_ac6_review_rejections_beyond_budget_fail_the_run() -> None:
    """AC6: after MAX_DEVELOPMENT_ATTEMPTS, a review rejection ends the run in FAILED."""
    run = _make_run()
    run.start()
    for attempt in range(1, MAX_DEVELOPMENT_ATTEMPTS + 1):
        run.development_completed()
        run.record_review_outcome(approved=False)
        expected_stage = (
            PipelineStage.FAILED
            if attempt == MAX_DEVELOPMENT_ATTEMPTS
            else PipelineStage.IMPLEMENTING
        )
        assert run.stage is expected_stage
    assert run.is_finished
    assert run.failure_reason == FAILED_REASON_TEMPLATE.format(attempts=MAX_DEVELOPMENT_ATTEMPTS)


def test_spec01_ac6_retry_budget_is_three_development_attempts() -> None:
    """AC6: the budget holds exactly three attempts, not whatever the constant becomes.

    The two other AC6 tests loop over MAX_DEVELOPMENT_ATTEMPTS, so they follow the
    implementation when its value changes. This test hard-codes the contract value
    from specs/01-domain-model.md so that raising or lowering it turns red.
    """
    run = _make_run()
    run.start()

    # The first two review rejections must start a new attempt instead of failing.
    for _ in range(2):
        run.development_completed()
        run.record_review_outcome(approved=False)
        assert run.stage is PipelineStage.IMPLEMENTING

    # The third rejection exhausts the budget.
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.FAILED
    assert run.development_attempts == 3
    assert run.failure_reason == FAILED_REASON_TEMPLATE.format(attempts=3)


def test_spec01_ac6_approval_at_last_attempt_opens_pull_request() -> None:
    """AC6: an approval on the last allowed attempt still opens the pull request."""
    run = _make_run()
    run.start()
    for _ in range(MAX_DEVELOPMENT_ATTEMPTS - 1):
        run.development_completed()
        run.record_review_outcome(approved=False)
    run.development_completed()
    run.record_review_outcome(approved=True)
    assert run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert run.is_finished
    assert run.failure_reason is None


def test_spec01_ac7_calls_from_wrong_stage_are_rejected() -> None:
    """AC7: pipeline methods raise InvalidStageTransitionError outside their stage."""
    fresh_run = _make_run()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.development_completed()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.record_review_outcome(approved=True)
    fresh_run.start()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.start()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.record_review_outcome(approved=True)
    finished_run = _make_run()
    _advance_to_pull_request_opened(finished_run)
    with pytest.raises(InvalidStageTransitionError):
        finished_run.development_completed()
    with pytest.raises(InvalidStageTransitionError):
        finished_run.record_review_outcome(approved=True)


@pytest.mark.parametrize(
    ("stage", "expected_role"),
    [
        (PipelineStage.IMPLEMENTING, AgentRole.DEVELOPER),
        (PipelineStage.REVIEW, AgentRole.CODE_REVIEWER),
        (PipelineStage.NEW, None),
        (PipelineStage.PULL_REQUEST_OPENED, None),
        (PipelineStage.FAILED, None),
    ],
)
def test_spec01_ac8_stage_role_mapping(
    stage: PipelineStage, expected_role: AgentRole | None
) -> None:
    """AC8: each agent-driven stage maps to its responsible agent role."""
    assert stage.role is expected_role


def test_spec07_ac1_pipeline_shape_and_roles() -> None:
    """AC1: the pipeline has one review stage and two active agent roles."""
    assert [stage.name for stage in PipelineStage] == [
        "NEW",
        "IMPLEMENTING",
        "REVIEW",
        "PULL_REQUEST_OPENED",
        "FAILED",
    ]
    assert MAX_DEVELOPMENT_ATTEMPTS == 3
    assert [role.name for role in AgentRole] == [
        "DEVELOPER",
        "CODE_REVIEWER",
    ]
    assert [stage.name for stage in PipelineStage if stage.role is not None] == [
        "IMPLEMENTING",
        "REVIEW",
    ]


def test_spec07_ac2_development_completed_enters_review() -> None:
    """AC2: a completed implementation goes straight to the single review stage."""
    run = _make_run()
    run.start()
    run.development_completed()
    assert run.stage is PipelineStage.REVIEW
    assert run.development_attempts == 1


def test_spec07_ac2_review_outcome_opens_pull_request() -> None:
    """AC2: an approved review opens the pull request."""
    run = _make_run()
    run.start()
    run.development_completed()
    run.record_review_outcome(approved=True)
    assert run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert run.is_finished
    assert run.failure_reason is None


def test_spec07_ac2_rejection_retries_then_exhausts_budget() -> None:
    """AC2: rejections retry until the shared three-attempt budget is exhausted."""
    run = _make_run()
    run.start()
    for _ in range(MAX_DEVELOPMENT_ATTEMPTS - 1):
        run.development_completed()
        run.record_review_outcome(approved=False)
        assert run.stage is PipelineStage.IMPLEMENTING
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.FAILED
    assert run.failure_reason == FAILED_REASON_TEMPLATE.format(attempts=MAX_DEVELOPMENT_ATTEMPTS)
