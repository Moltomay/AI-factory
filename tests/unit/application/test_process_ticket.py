"""Behavior tests for the ProcessTicket use case, using in-memory fake ports."""

import pytest

from ai_factory.application.process_ticket import ProcessTicket
from ai_factory.domain.outcomes import StageOutcome
from ai_factory.domain.pipeline import FAILED_REASON_TEMPLATE, PipelineStage
from ai_factory.domain.quality_gate import CHECKS_FAILED_FINDING
from ai_factory.domain.ticket import Ticket
from tests.unit.application.fakes import (
    FakeCodeAgent,
    FakeQualityRunner,
    FakeTicketSource,
    FakeVersionControl,
)


def _make_ticket() -> Ticket:
    return Ticket(
        ticket_id="42",
        title="Add the export endpoint",
        description="Export the data as CSV.",
    )


def _outcome(approved: bool, summary: str, findings: tuple[str, ...] = ()) -> StageOutcome:
    return StageOutcome(approved=approved, summary=summary, findings=findings)


def test_spec02_ac1_ac6_happy_path_opens_pull_request_reported_once() -> None:
    """AC1/AC6: full call order, PR opened with the ticket content, reported once."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log, [_outcome(True, "QA approves.")], [_outcome(True, "Review approves.")]
    )
    runner = FakeQualityRunner(log, [True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert log == [
        "create_branch:factory/42",
        "implement",
        "run_checks",
        "quality_review",
        "final_review",
        "publish_pull_request",
        "report_result",
    ]
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert result.run.development_attempts == 1
    assert result.pull_request_url == version_control.pull_request_url
    assert version_control.published == [("factory/42", ticket.title, ticket.description)]
    assert source.reported == [(ticket, f"Pull request opened: {version_control.pull_request_url}")]


def test_spec02_ac2_quality_failure_feeds_findings_to_next_attempt() -> None:
    """AC2: a rejected quality check retries development with its findings."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [
            _outcome(False, "Missing validation.", ("Validate the CSV header.",)),
            _outcome(True, "OK."),
        ],
        [_outcome(True, "Review approves.")],
    )
    runner = FakeQualityRunner(log, [True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert agent.implemented_with == [(), ("Validate the CSV header.",)]
    assert result.run.development_attempts == 2
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec02_ac3_failed_checks_feed_synthetic_finding_to_retry() -> None:
    """AC3: failing checks reject the QA stage and surface the synthetic finding."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [_outcome(True, "QA agent approves."), _outcome(True, "QA agent approves.")],
        [_outcome(True, "Review approves.")],
    )
    runner = FakeQualityRunner(log, [False, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert agent.implemented_with == [(), (CHECKS_FAILED_FINDING,)]
    assert result.run.development_attempts == 2
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec02_ac4_review_failure_feeds_its_findings_to_next_attempt() -> None:
    """AC4: a rejected final review retries development with its findings."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [_outcome(True, "OK."), _outcome(True, "OK.")],
        [_outcome(False, "Naming is unclear.", ("Rename parse_csv.",)), _outcome(True, "OK.")],
    )
    runner = FakeQualityRunner(log, [True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert agent.implemented_with == [(), ("Rename parse_csv.",)]
    assert result.run.development_attempts == 2
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec02_ac5_ac6_exhausted_budget_fails_without_pull_request() -> None:
    """AC5/AC6: three rejections fail the run, reported exactly once, no PR."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [
            _outcome(False, "Still wrong."),
            _outcome(False, "Still wrong."),
            _outcome(False, "Still wrong."),
        ],
        [],
    )
    runner = FakeQualityRunner(log, [True, True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    expected_reason = FAILED_REASON_TEMPLATE.format(attempts=3)
    assert result.run.stage is PipelineStage.FAILED
    assert result.run.failure_reason == expected_reason
    assert result.pull_request_url is None
    assert version_control.published == []
    assert source.reported == [(ticket, f"Automated processing failed: {expected_reason}")]


class _ExplodingCodeAgent(FakeCodeAgent):
    """Code agent whose implementation always crashes (AC7)."""

    def implement(self, ticket: Ticket, feedback: tuple[str, ...]) -> None:
        raise RuntimeError("code agent crashed")


def test_spec02_ac7_port_exception_propagates_without_pull_request_or_report() -> None:
    """AC7: a crashing port propagates; nothing is published or reported."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = _ExplodingCodeAgent(log, [], [])
    runner = FakeQualityRunner(log, [])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    with pytest.raises(RuntimeError, match="code agent crashed"):
        use_case.execute(ticket)

    assert version_control.published == []
    assert source.reported == []


def test_spec02_ac8_branch_created_once_despite_retries() -> None:
    """AC8: the working branch is created a single time even after retries."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [_outcome(False, "KO."), _outcome(True, "OK.")],
        [_outcome(True, "Review approves.")],
    )
    runner = FakeQualityRunner(log, [True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    use_case.execute(ticket)

    assert version_control.created_branches == ["factory/42"]
