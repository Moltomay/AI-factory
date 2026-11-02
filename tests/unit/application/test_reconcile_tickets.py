"""Behavior tests for the ReconcileTickets use case, using in-memory fake ports."""

from ai_factory.application.ports import PullRequestState, TicketStatus
from ai_factory.application.reconcile_tickets import ReconcileTickets
from ai_factory.domain.ticket import Ticket
from tests.unit.application.fakes import FakeTicketSource, FakeVersionControl


def _make_ticket(ticket_id: str) -> Ticket:
    return Ticket(ticket_id=ticket_id, title=f"Ticket {ticket_id}", description="")


def _make_use_case(
    log: list[str],
    states_by_branch: dict[str, PullRequestState],
    *cards: Ticket,
) -> tuple[ReconcileTickets, FakeTicketSource]:
    source = FakeTicketSource(log, {TicketStatus.IN_REVIEW: list(cards)})
    version_control = FakeVersionControl(log, states_by_branch=states_by_branch)
    return ReconcileTickets(source, version_control), source


def test_spec06b_ac6_merged_pull_request_moves_the_card_to_done_without_comment() -> None:
    """AC6: a merged pull request sends the card to Done and posts nothing."""
    log: list[str] = []
    ticket = _make_ticket("42")
    use_case, source = _make_use_case(log, {"factory/42": PullRequestState.MERGED}, ticket)

    result = use_case.execute()

    assert source.cards_by_status[TicketStatus.DONE] == [ticket]
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == []
    assert source.reported == []
    assert result.merged == (ticket,)
    assert not result.failed


def test_spec06b_ac7_closed_pull_request_moves_to_todo_then_comments_the_branch() -> None:
    """AC7: a closed pull request sends the card back to To Do, then comments."""
    log: list[str] = []
    ticket = _make_ticket("42")
    use_case, source = _make_use_case(log, {"factory/42": PullRequestState.CLOSED}, ticket)

    result = use_case.execute()

    assert source.cards_by_status[TicketStatus.TODO] == [ticket]
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == []
    assert len(source.reported) == 1
    assert "factory/42" in source.reported[0][1]
    assert log.index("set_status:todo") < log.index("report_result")
    assert result.closed == (ticket,)


def test_spec06b_ac8_open_pull_request_leaves_the_card_untouched() -> None:
    """AC8: an open pull request means no move and no comment."""
    log: list[str] = []
    ticket = _make_ticket("42")
    use_case, source = _make_use_case(log, {"factory/42": PullRequestState.OPEN}, ticket)

    result = use_case.execute()

    assert source.cards_by_status[TicketStatus.IN_REVIEW] == [ticket]
    assert source.cards_by_status[TicketStatus.TODO] == []
    assert source.cards_by_status[TicketStatus.DONE] == []
    assert source.reported == []
    assert result.still_open == (ticket,)
    assert not result.failed


def test_spec06b_ac9_missing_pull_request_is_skipped_and_the_others_are_processed() -> None:
    """AC9: a card without a pull request is kept, the next cards still move."""
    log: list[str] = []
    missing = _make_ticket("1")
    merged = _make_ticket("2")
    use_case, source = _make_use_case(
        log,
        {
            "factory/1": PullRequestState.NOT_FOUND,
            "factory/2": PullRequestState.MERGED,
        },
        missing,
        merged,
    )

    result = use_case.execute()

    assert source.cards_by_status[TicketStatus.IN_REVIEW] == [missing]
    assert source.cards_by_status[TicketStatus.DONE] == [merged]
    assert result.not_found == (missing,)
    assert result.merged == (merged,)
    assert result.failed


def test_spec06b_ac10_second_run_without_state_change_moves_and_comments_nothing() -> None:
    """AC10: only In Review cards are scanned, so a second run is a no-op."""
    log: list[str] = []
    merged = _make_ticket("1")
    closed = _make_ticket("2")
    still_open = _make_ticket("3")
    use_case, source = _make_use_case(
        log,
        {
            "factory/1": PullRequestState.MERGED,
            "factory/2": PullRequestState.CLOSED,
            "factory/3": PullRequestState.OPEN,
        },
        merged,
        closed,
        still_open,
    )

    use_case.execute()
    reports_after_first_run = list(source.reported)
    todo_after_first_run = list(source.cards_by_status[TicketStatus.TODO])
    done_after_first_run = list(source.cards_by_status[TicketStatus.DONE])

    second_result = use_case.execute()

    assert source.cards_by_status[TicketStatus.TODO] == todo_after_first_run
    assert source.cards_by_status[TicketStatus.DONE] == done_after_first_run
    assert source.cards_by_status[TicketStatus.IN_REVIEW] == [still_open]
    assert source.reported == reports_after_first_run
    assert second_result.merged == ()
    assert second_result.closed == ()
    assert second_result.still_open == (still_open,)
    assert not second_result.failed


def test_spec06b_ac10_empty_review_list_reports_nothing_to_do() -> None:
    """AC10: an empty In Review list produces an empty, successful result."""
    log: list[str] = []
    use_case, source = _make_use_case(log, {})

    result = use_case.execute()

    assert source.reported == []
    assert result.merged == ()
    assert result.closed == ()
    assert result.still_open == ()
    assert not result.failed
