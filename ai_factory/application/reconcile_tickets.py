"""Reconcile-tickets use case: apply the pull request outcome to In Review cards."""

from dataclasses import dataclass

from ai_factory.application.ports import (
    PullRequestState,
    TicketSource,
    TicketStatus,
    VersionControl,
)
from ai_factory.application.process_ticket import BRANCH_NAME_TEMPLATE
from ai_factory.domain.ticket import Ticket

CLOSED_MESSAGE_TEMPLATE = "Pull request closed without merging: branch {branch_name}"


@dataclass(frozen=True)
class ReconcileResult:
    """Aggregated outcome of one reconcile run.

    Attributes:
        merged: Tickets moved to Done.
        closed: Tickets moved back to To Do and commented.
        still_open: Tickets left in In Review because their pull request is open.
        not_found: Tickets left in In Review because no pull request was found.
    """

    merged: tuple[Ticket, ...]
    closed: tuple[Ticket, ...]
    still_open: tuple[Ticket, ...]
    not_found: tuple[Ticket, ...]

    @property
    def failed(self) -> bool:
        """Whether at least one ticket had no pull request."""
        return bool(self.not_found)


class ReconcileTickets:
    """Apply the pull request outcome to every card sitting In Review.

    Only In Review cards are scanned, so a card already moved to Done or back
    to To Do is never seen again: running twice without a state change is a
    no-op.
    """

    def __init__(self, ticket_source: TicketSource, version_control: VersionControl) -> None:
        """Wire the use case to its ports.

        Args:
            ticket_source: Tracker holding the In Review cards.
            version_control: Source of the pull request state per branch.
        """
        self._ticket_source = ticket_source
        self._version_control = version_control

    def execute(self) -> ReconcileResult:
        """Reconcile every In Review card and aggregate the outcome.

        Returns:
            The tickets moved to Done, moved back to To Do, left open and left
            without a pull request.
        """
        merged: list[Ticket] = []
        closed: list[Ticket] = []
        still_open: list[Ticket] = []
        not_found: list[Ticket] = []
        for ticket in self._ticket_source.list_by_status(TicketStatus.IN_REVIEW):
            branch_name = BRANCH_NAME_TEMPLATE.format(ticket_id=ticket.ticket_id)
            state = self._version_control.pull_request_state(branch_name)
            if state is PullRequestState.MERGED:
                self._ticket_source.set_status(ticket, TicketStatus.DONE)
                merged.append(ticket)
            elif state is PullRequestState.CLOSED:
                self._ticket_source.set_status(ticket, TicketStatus.TODO)
                self._ticket_source.report_result(
                    ticket, CLOSED_MESSAGE_TEMPLATE.format(branch_name=branch_name)
                )
                closed.append(ticket)
            elif state is PullRequestState.OPEN:
                still_open.append(ticket)
            else:
                not_found.append(ticket)
        return ReconcileResult(
            merged=tuple(merged),
            closed=tuple(closed),
            still_open=tuple(still_open),
            not_found=tuple(not_found),
        )
