"""AC4-AC8: pipeline state machine, retry budget and role mapping."""

import pytest

from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.pipeline import (
    CLARIFICATION_REASON_TEMPLATE,
    FAILED_REASON_TEMPLATE,
    MAX_DEVELOPMENT_ATTEMPTS,
    AgentRole,
    PipelineRun,
    PipelineStage,
)
from ai_factory.domain.specification import AcceptanceCriterion, Specification
from ai_factory.domain.ticket import Ticket


def _make_run() -> PipelineRun:
    return PipelineRun(ticket=Ticket(ticket_id="card-1", title="Do the thing", description=""))


def _make_specification() -> Specification:
    return Specification(
        problem="The thing is not done.",
        scope_in=("Do the thing.",),
        scope_out=(),
        acceptance_criteria=(
            AcceptanceCriterion(
                id="AC1",
                statement="The thing is done.",
                ticket_quote="Do the thing",
            ),
        ),
        unknowns=(),
        definition_of_done=("The thing is tested.",),
    )


def _start_with_specification(run: PipelineRun) -> Specification:
    run.start()
    specification = _make_specification()
    run.specification_completed(specification)
    return specification


def _advance_to_pull_request_opened(run: PipelineRun) -> None:
    _start_with_specification(run)
    run.development_completed()
    run.record_review_outcome(approved=True)


def test_spec01_ac4_happy_path_reaches_pull_request_opened() -> None:
    """AC4: a fully approved run ends with the PR opened and one attempt."""
    run = _make_run()
    assert run.stage is PipelineStage.NEW
    assert not run.is_finished
    run.start()
    assert run.stage is PipelineStage.SPECIFYING
    assert run.development_attempts == 0
    specification = _make_specification()
    run.specification_completed(specification)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 1
    assert run.specification is specification
    run.development_completed()
    assert run.stage is PipelineStage.REVIEW
    run.record_review_outcome(approved=True)
    assert run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert run.is_finished
    assert run.failure_reason is None


def test_spec01_ac5_review_rejection_sends_back_to_implementing() -> None:
    """AC5: a review rejection starts a new development attempt."""
    run = _make_run()
    _start_with_specification(run)
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 2


def test_spec01_ac5_second_review_rejection_starts_another_attempt() -> None:
    """AC5: every rejection before the budget starts a fresh attempt."""
    run = _make_run()
    _start_with_specification(run)
    run.development_completed()
    run.record_review_outcome(approved=False)
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 3


def test_spec01_ac6_review_rejections_beyond_budget_fail_the_run() -> None:
    """AC6: after MAX_DEVELOPMENT_ATTEMPTS, a review rejection ends the run in FAILED."""
    run = _make_run()
    _start_with_specification(run)
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
    _start_with_specification(run)

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
    _start_with_specification(run)
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
        fresh_run.specification_completed(_make_specification())
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.clarification_requested(("Which format?",))
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.development_completed()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.record_review_outcome(approved=True)
    fresh_run.start()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.start()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.development_completed()
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.record_review_outcome(approved=True)
    fresh_run.specification_completed(_make_specification())
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.specification_completed(_make_specification())
    with pytest.raises(InvalidStageTransitionError):
        fresh_run.clarification_requested(("Which format?",))
    finished_run = _make_run()
    _advance_to_pull_request_opened(finished_run)
    with pytest.raises(InvalidStageTransitionError):
        finished_run.development_completed()
    with pytest.raises(InvalidStageTransitionError):
        finished_run.record_review_outcome(approved=True)
    with pytest.raises(InvalidStageTransitionError):
        finished_run.specification_completed(_make_specification())


@pytest.mark.parametrize(
    ("stage", "expected_role"),
    [
        (PipelineStage.SPECIFYING, AgentRole.SPEC_WRITER),
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


def test_spec06e_ac1_pipeline_shape_and_roles() -> None:
    """AC1: the pipeline has one spec stage, one review stage and three roles."""
    assert [stage.name for stage in PipelineStage] == [
        "NEW",
        "SPECIFYING",
        "IMPLEMENTING",
        "REVIEW",
        "PULL_REQUEST_OPENED",
        "FAILED",
    ]
    assert MAX_DEVELOPMENT_ATTEMPTS == 3
    assert [role.name for role in AgentRole] == [
        "SPEC_WRITER",
        "DEVELOPER",
        "CODE_REVIEWER",
    ]
    assert [stage.name for stage in PipelineStage if stage.role is not None] == [
        "SPECIFYING",
        "IMPLEMENTING",
        "REVIEW",
    ]


def test_spec06e_ac2_start_opens_specifying_without_development_attempt() -> None:
    """AC2: start moves NEW to SPECIFYING and starts no development attempt."""
    run = _make_run()
    run.start()
    assert run.stage is PipelineStage.SPECIFYING
    assert run.development_attempts == 0
    assert run.specification is None
    assert not run.is_finished


def test_spec06e_ac2_specification_completed_stores_the_spec_and_starts_development() -> None:
    """AC2: a validated specification moves to IMPLEMENTING with the first attempt."""
    run = _make_run()
    run.start()
    specification = _make_specification()
    run.specification_completed(specification)
    assert run.stage is PipelineStage.IMPLEMENTING
    assert run.development_attempts == 1
    assert run.specification is specification
    assert run.failure_reason is None


def test_spec06e_ac2_clarification_requested_fails_with_the_questions() -> None:
    """AC2: an ambiguous ticket fails the run and reports its questions."""
    run = _make_run()
    run.start()
    questions = ("Which export format?", "Which columns?")
    run.clarification_requested(questions)
    assert run.stage is PipelineStage.FAILED
    assert run.is_finished
    assert run.development_attempts == 0
    assert run.failure_reason == CLARIFICATION_REASON_TEMPLATE.format(
        questions=" | ".join(questions)
    )
    for question in questions:
        assert question in run.failure_reason


def test_spec06e_ac2_new_transitions_reject_a_wrong_stage() -> None:
    """AC2: the spec transitions only run from SPECIFYING."""
    run = _make_run()
    run.start()
    run.specification_completed(_make_specification())
    with pytest.raises(InvalidStageTransitionError):
        run.clarification_requested(("Too late?",))
    with pytest.raises(InvalidStageTransitionError):
        run.specification_completed(_make_specification())
    failed_run = _make_run()
    failed_run.start()
    failed_run.clarification_requested(("Which format?",))
    with pytest.raises(InvalidStageTransitionError):
        failed_run.specification_completed(_make_specification())


def test_spec07_ac2_development_completed_enters_review() -> None:
    """AC2: a completed implementation goes straight to the single review stage."""
    run = _make_run()
    _start_with_specification(run)
    run.development_completed()
    assert run.stage is PipelineStage.REVIEW
    assert run.development_attempts == 1


def test_spec07_ac2_review_outcome_opens_pull_request() -> None:
    """AC2: an approved review opens the pull request."""
    run = _make_run()
    _start_with_specification(run)
    run.development_completed()
    run.record_review_outcome(approved=True)
    assert run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert run.is_finished
    assert run.failure_reason is None


def test_spec07_ac2_rejection_retries_then_exhausts_budget() -> None:
    """AC2: rejections retry until the shared three-attempt budget is exhausted."""
    run = _make_run()
    _start_with_specification(run)
    for _ in range(MAX_DEVELOPMENT_ATTEMPTS - 1):
        run.development_completed()
        run.record_review_outcome(approved=False)
        assert run.stage is PipelineStage.IMPLEMENTING
    run.development_completed()
    run.record_review_outcome(approved=False)
    assert run.stage is PipelineStage.FAILED
    assert run.failure_reason == FAILED_REASON_TEMPLATE.format(attempts=MAX_DEVELOPMENT_ATTEMPTS)
