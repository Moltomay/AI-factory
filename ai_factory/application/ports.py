"""Application ports: protocols isolating the process-ticket use case from the outside world.

They sit in the application layer between the domain rules and the infrastructure
adapters (see ARCHITECTURE.md): the use case depends only on these protocols.
"""

from enum import Enum
from typing import Protocol

from ai_factory.domain.outcomes import StageOutcome
from ai_factory.domain.ticket import Ticket


class TicketStatus(Enum):
    """Where a ticket sits in the tracker workflow."""

    TODO = "todo"
    IN_REVIEW = "in_review"
    DONE = "done"


class PullRequestState(Enum):
    """Lifecycle state of the pull request attached to a branch."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
    NOT_FOUND = "not_found"


class TicketSource(Protocol):
    """Tracker-side operations the pipeline needs."""

    def fetch_next_ticket(self) -> Ticket | None:
        """Return the next ticket waiting to be processed.

        Returns:
            The next ticket, or None when no ticket is waiting.
        """
        ...

    def report_result(self, ticket: Ticket, message: str) -> None:
        """Attach the final processing result (success or failure) to the ticket.

        Args:
            ticket: The processed ticket.
            message: Human-readable outcome, e.g. the pull request URL.
        """
        ...

    def list_by_status(self, status: TicketStatus) -> list[Ticket]:
        """Return the tickets currently sitting in the list matching the status.

        Args:
            status: Workflow status whose list should be read.

        Returns:
            The tickets in that list, in tracker order.
        """
        ...

    def set_status(self, ticket: Ticket, status: TicketStatus) -> None:
        """Move the ticket to the list matching the status.

        Args:
            ticket: The ticket whose card must move.
            status: Destination status.
        """
        ...


class CodeAgent(Protocol):
    """LLM coding agent able to implement and review changes in the working copy."""

    def implement(self, ticket: Ticket, feedback: tuple[str, ...]) -> None:
        """Make the change requested by the ticket in the working copy.

        Args:
            ticket: The ticket describing the requested change.
            feedback: Findings from the previous failed attempt; empty on the
                first attempt.
        """
        ...

    def quality_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        """Review the current working copy as the quality analyst.

        Args:
            ticket: The ticket being processed.
            feedback: Findings from the previous failed attempt; empty on the
                first attempt.

        Returns:
            The quality analyst's verdict on the working copy.
        """
        ...

    def final_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        """Review the current working copy as the final reviewer.

        Args:
            ticket: The ticket being processed.
            feedback: Findings from the previous failed attempt; empty on the
                first attempt.

        Returns:
            The final reviewer's verdict on the working copy.
        """
        ...


class QualityRunner(Protocol):
    """Deterministic quality checks (lint, tests) on the working copy."""

    def run_checks(self) -> bool:
        """Run the deterministic checks on the working copy.

        Returns:
            True when every check passed, False otherwise.
        """
        ...


class VersionControl(Protocol):
    """Git operations needed to publish a ticket's change as a pull request."""

    def create_branch(self, branch_name: str) -> None:
        """Create the working branch for a ticket.

        Args:
            branch_name: Name of the branch to create from the base branch.
        """
        ...

    def publish_pull_request(self, branch_name: str, title: str, body: str) -> str:
        """Commit and push the working copy, then open a pull request.

        Args:
            branch_name: Branch holding the change.
            title: Pull request title.
            body: Pull request description.

        Returns:
            The URL of the opened pull request.
        """
        ...

    def pull_request_state(self, branch_name: str) -> PullRequestState:
        """Return what happened to the pull request opened from the branch.

        Args:
            branch_name: Branch the pull request was opened from.

        Returns:
            The pull request state, or NOT_FOUND when no pull request exists.
        """
        ...

    def delete_branch(self, branch_name: str) -> None:
        """Delete the remote branch, doing nothing when it is already gone.

        Args:
            branch_name: Branch to delete from the remote repository.
        """
        ...
