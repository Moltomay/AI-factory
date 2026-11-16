"""In-memory fake ports for the application use case tests (no network, no git)."""

from ai_factory.application.ports import PullRequestState, TicketStatus
from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.outcomes import ReviewFeedback, StageOutcome
from ai_factory.domain.specification import Specification, SpecOutcome
from ai_factory.domain.ticket import Ticket


class FakeTicketSource:
    """Ticket source backed by in-memory status lists, recording every call."""

    def __init__(
        self,
        log: list[str],
        cards_by_status: dict[TicketStatus, list[Ticket]] | None = None,
    ) -> None:
        """Build the lists from the given cards and start recording calls.

        Args:
            log: Shared call log, appended to by every operation.
            cards_by_status: Initial cards per list; missing lists start empty.
        """
        self.log = log
        self.reported: list[tuple[Ticket, str]] = []
        self.cards_by_status: dict[TicketStatus, list[Ticket]] = {
            status: [] for status in TicketStatus
        }
        for status, tickets in (cards_by_status or {}).items():
            self.cards_by_status[status] = list(tickets)

    def report_result(self, ticket: Ticket, message: str) -> None:
        self.log.append("report_result")
        self.reported.append((ticket, message))

    def list_by_status(self, status: TicketStatus) -> list[Ticket]:
        self.log.append(f"list_by_status:{status.value}")
        return list(self.cards_by_status[status])

    def set_status(self, ticket: Ticket, status: TicketStatus) -> None:
        """Move the ticket to the target list, recording the transition."""
        self.log.append(f"set_status:{status.value}")
        for tickets in self.cards_by_status.values():
            if ticket in tickets:
                tickets.remove(ticket)
        self.cards_by_status[status].append(ticket)


class FakeSpecAgent:
    """Scripted spec agent: replays queued outcomes and records calls."""

    def __init__(self, log: list[str], outcomes: list[SpecOutcome]) -> None:
        """Queue the outcomes and start recording calls.

        Args:
            log: Shared call log, appended to by every operation.
            outcomes: Spec outcomes replayed in order, one per specify call.
        """
        self.log = log
        self.outcomes = outcomes
        self.specified: list[Ticket] = []

    def specify(self, ticket: Ticket) -> SpecOutcome:
        self.log.append("specify")
        self.specified.append(ticket)
        return self.outcomes.pop(0)


class FakeCodeAgent:
    """Scripted code agent: replays queued review verdicts and records calls.

    Review calls pop the next verdict of their queue, so tests spell out the
    full sequence of attempts.

    Attributes:
        implemented_with: Feedback received by each implement call, in order.
        implemented_specifications: Specification received by each implement call.
        reviewed_specifications: Specification received by each review call.
    """

    def __init__(
        self,
        log: list[str],
        review_verdicts: list[StageOutcome],
    ) -> None:
        self.log = log
        self.review_verdicts = review_verdicts
        self.implemented_with: list[ReviewFeedback] = []
        self.implemented_specifications: list[Specification] = []
        self.reviewed_specifications: list[Specification] = []

    def implement(
        self, ticket: Ticket, specification: Specification, feedback: ReviewFeedback
    ) -> None:
        self.log.append("implement")
        self.implemented_with.append(feedback)
        self.implemented_specifications.append(specification)

    def review(
        self, ticket: Ticket, specification: Specification, feedback: ReviewFeedback
    ) -> StageOutcome:
        self.log.append("review")
        self.reviewed_specifications.append(specification)
        return self.review_verdicts.pop(0)


class FakeQualityRunner:
    """Replays queued check results, one per run_checks call."""

    def __init__(self, log: list[str], results: list[bool]) -> None:
        self.log = log
        self.results = results

    def run_checks(self) -> bool:
        self.log.append("run_checks")
        return self.results.pop(0)


class FakeVersionControl:
    """Records branches and pull requests instead of touching git."""

    def __init__(
        self,
        log: list[str],
        pull_request_url: str = "https://example.test/pr/1",
        states_by_branch: dict[str, PullRequestState] | None = None,
        default_state: PullRequestState = PullRequestState.OPEN,
        branch_delete_failures: set[str] | None = None,
    ) -> None:
        """Configure the recorded branches, pull request states and failures.

        Args:
            log: Shared call log, appended to by every operation.
            pull_request_url: URL returned when a pull request is published.
            states_by_branch: Pull request state per branch.
            default_state: State used for a branch absent from the mapping.
            branch_delete_failures: Branches whose deletion must raise.
        """
        self.log = log
        self.pull_request_url = pull_request_url
        self.created_branches: list[str] = []
        self.published: list[tuple[str, str, str]] = []
        self.deleted_branches: list[str] = []
        self.states_by_branch = dict(states_by_branch or {})
        self.default_state = default_state
        self.branch_delete_failures = set(branch_delete_failures or ())

    def create_branch(self, branch_name: str) -> None:
        self.log.append(f"create_branch:{branch_name}")
        self.created_branches.append(branch_name)

    def publish_pull_request(self, branch_name: str, title: str, body: str) -> str:
        self.log.append("publish_pull_request")
        self.published.append((branch_name, title, body))
        return self.pull_request_url

    def pull_request_state(self, branch_name: str) -> PullRequestState:
        self.log.append(f"pull_request_state:{branch_name}")
        return self.states_by_branch.get(branch_name, self.default_state)

    def delete_branch(self, branch_name: str) -> None:
        """Record the deletion, raising for a branch configured to fail."""
        self.log.append(f"delete_branch:{branch_name}")
        if branch_name in self.branch_delete_failures:
            raise ExternalServiceError(f"could not delete branch {branch_name}")
        self.deleted_branches.append(branch_name)
