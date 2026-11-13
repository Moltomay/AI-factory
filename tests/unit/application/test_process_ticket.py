"""Behavior tests for the ProcessTicket use case, using in-memory fake ports."""

import dataclasses

import pytest

from ai_factory.application.ports import CodeAgent, TicketStatus
from ai_factory.application.process_ticket import ProcessTicket
from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from ai_factory.domain.outcomes import ReviewFeedback, StageOutcome
from ai_factory.domain.pipeline import FAILED_REASON_TEMPLATE, PipelineStage
from ai_factory.domain.quality_gate import DETERMINISTIC_FAILURE_LOCATION
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


def _blocker(message: str) -> Finding:
    return Finding(
        severity=FindingSeverity.BLOCKER,
        category=FindingCategory.TESTS,
        location="src/export.py:10",
        message=message,
        status=FindingStatus.UNVERIFIED,
    )


def _minor(message: str) -> Finding:
    return dataclasses.replace(_blocker(message), severity=FindingSeverity.MINOR)


def _approved(*findings: Finding) -> StageOutcome:
    return StageOutcome(summary="Approves.", findings=findings)


def _rejected(*findings: Finding) -> StageOutcome:
    return StageOutcome(summary="Rejected.", findings=findings)


def test_spec02_ac1_ac6_happy_path_opens_pull_request_reported_once() -> None:
    """AC1/AC6: full call order, PR opened with the ticket content, reported once."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(log, [_approved()])
    runner = FakeQualityRunner(log, [True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert log == [
        "create_branch:factory/42",
        "implement",
        "run_checks",
        "review",
        "publish_pull_request",
        "set_status:in_review",
        "report_result",
    ]
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED
    assert result.run.development_attempts == 1
    assert result.pull_request_url == version_control.pull_request_url
    assert version_control.published == [("factory/42", ticket.title, ticket.description)]
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == [ticket]
    assert source.reported == [(ticket, f"Pull request opened: {version_control.pull_request_url}")]


def test_spec06b_ac5_success_moves_the_card_before_commenting() -> None:
    """AC5: the card reaches In Review before the pull request URL is commented."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log, {TicketStatus.TODO: [ticket]})
    agent = FakeCodeAgent(log, [_approved()])
    runner = FakeQualityRunner(log, [True])
    use_case = ProcessTicket(source, agent, runner, FakeVersionControl(log))

    use_case.execute(ticket)

    assert source.cards_by_status[TicketStatus.TODO] == []
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == [ticket]
    assert log.index("set_status:in_review") < log.index("report_result")


def test_spec06b_ac5_failure_reports_without_moving_the_card() -> None:
    """AC5: a failed run comments on the failure and leaves the card in To Do."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log, {TicketStatus.TODO: [ticket]})
    agent = FakeCodeAgent(
        log,
        [
            _rejected(_blocker("Still wrong.")),
            _rejected(_blocker("Still wrong.")),
            _rejected(_blocker("Still wrong.")),
        ],
    )
    runner = FakeQualityRunner(log, [True, True, True])
    use_case = ProcessTicket(source, agent, runner, FakeVersionControl(log))

    result = use_case.execute(ticket)

    assert result.pull_request_url is None
    assert source.cards_by_status[TicketStatus.TODO] == [ticket]
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == []
    assert source.reported[0][0] == ticket
    assert "Automated processing failed" in source.reported[0][1]


def test_spec02_ac2_review_failure_feeds_findings_to_next_attempt() -> None:
    """AC2: a rejected review retries development with its findings."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    blocker = _blocker("Validate the CSV header.")
    agent = FakeCodeAgent(log, [_rejected(blocker), _approved()])
    runner = FakeQualityRunner(log, [True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert agent.implemented_with[0] == ReviewFeedback()
    assert agent.implemented_with[1].findings == (blocker,)
    assert result.run.development_attempts == 2
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec07_ac3_red_gate_skips_the_review_agent() -> None:
    """AC3: a red deterministic gate never reaches the review agent."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(log, [_approved()])
    runner = FakeQualityRunner(log, [False, True])
    use_case = ProcessTicket(source, agent, runner, FakeVersionControl(log))

    result = use_case.execute(ticket)

    assert log.count("run_checks") == 2
    assert log.count("review") == 1
    assert agent.implemented_with[0] == ReviewFeedback()
    deterministic_finding = agent.implemented_with[1].findings[0]
    assert deterministic_finding.severity is FindingSeverity.BLOCKER
    assert deterministic_finding.location == DETERMINISTIC_FAILURE_LOCATION
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec07_ac3_green_gate_calls_review_once() -> None:
    """AC3: a green gate calls the single review agent exactly once."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(log, [_approved()])
    runner = FakeQualityRunner(log, [True])
    use_case = ProcessTicket(source, agent, runner, FakeVersionControl(log))

    result = use_case.execute(ticket)

    assert log.count("run_checks") == 1
    assert log.count("review") == 1
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec02_ac4_review_failure_after_retry_feeds_new_findings() -> None:
    """AC4: each rejected review sends its own findings to the next attempt."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    first_blocker = _blocker("Rename parse_csv.")
    second_blocker = _blocker("Validate the CSV header.")
    agent = FakeCodeAgent(
        log,
        [_rejected(first_blocker), _rejected(second_blocker), _approved()],
    )
    runner = FakeQualityRunner(log, [True, True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    result = use_case.execute(ticket)

    assert agent.implemented_with[0] == ReviewFeedback()
    assert agent.implemented_with[1].findings == (first_blocker,)
    assert agent.implemented_with[2].findings == (second_blocker,)
    assert result.run.development_attempts == 3
    assert result.run.stage is PipelineStage.PULL_REQUEST_OPENED


def test_spec02_ac5_ac6_exhausted_budget_fails_without_pull_request() -> None:
    """AC5/AC6: three rejections fail the run, reported exactly once, no PR."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [
            _rejected(_blocker("Still wrong.")),
            _rejected(_blocker("Still wrong.")),
            _rejected(_blocker("Still wrong.")),
        ],
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

    def implement(self, ticket: Ticket, feedback: ReviewFeedback) -> None:
        raise RuntimeError("code agent crashed")


def test_spec02_ac7_port_exception_propagates_without_pull_request_or_report() -> None:
    """AC7: a crashing port propagates; nothing is published or reported."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = _ExplodingCodeAgent(log, [])
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
    agent = FakeCodeAgent(log, [_rejected(_blocker("KO.")), _approved()])
    runner = FakeQualityRunner(log, [True, True])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, runner, version_control)

    use_case.execute(ticket)

    assert version_control.created_branches == ["factory/42"]


def test_spec06d_ac10_minor_findings_reach_the_pull_request_body() -> None:
    """AC10: non-blocking findings stay visible to the human reviewer."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [_approved(_minor("Rename the helper."), _minor("Document the flag."))],
    )
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, FakeQualityRunner(log, [True]), version_control)

    use_case.execute(ticket)

    body = version_control.published[0][2]
    assert body.startswith(ticket.description)
    assert "## Automated review" in body
    assert "Rename the helper." in body
    assert "Document the flag." in body
    assert "src/export.py:10" in body


def test_spec06d_ac10_minor_findings_carry_their_ac_and_evidence() -> None:
    """AC10: a minor finding keeps its AC reference and its proof in the PR body."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    finding = dataclasses.replace(
        _minor("Cover the empty header."),
        ac="AC3",
        evidence="def test_empty_header_is_refused",
    )
    agent = FakeCodeAgent(log, [_approved(finding)])
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, FakeQualityRunner(log, [True]), version_control)

    use_case.execute(ticket)

    body = version_control.published[0][2]
    assert "(AC3)" in body
    assert "def test_empty_header_is_refused" in body


def test_spec06d_ac10_minors_from_a_rejected_attempt_are_not_published() -> None:
    """AC10: a retry invalidates the findings of the failed attempt."""
    log: list[str] = []
    ticket = _make_ticket()
    source = FakeTicketSource(log)
    agent = FakeCodeAgent(
        log,
        [_rejected(_blocker("Fix it."), _minor("Stale cosmetic nit.")), _approved()],
    )
    version_control = FakeVersionControl(log)
    use_case = ProcessTicket(source, agent, FakeQualityRunner(log, [True, True]), version_control)

    use_case.execute(ticket)

    assert version_control.published == [("factory/42", ticket.title, ticket.description)]


def test_spec07_ac4_code_agent_port_exposes_implement_and_review_only() -> None:
    """AC4: the port is consolidated to one implementation and one review call."""
    assert hasattr(CodeAgent, "implement")
    assert hasattr(CodeAgent, "review")
    assert not hasattr(CodeAgent, "quality_review")
    assert not hasattr(CodeAgent, "final_review")
