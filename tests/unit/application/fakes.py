"""In-memory fake ports for the application use case tests (no network, no git)."""

from ai_factory.application.ports import PullRequestState, TicketStatus
from ai_factory.domain.outcomes import StageOutcome
from ai_factory.domain.ticket import Ticket


class FakeTicketSource:
    """Ticket source backed by in-memory status lists, recording every call."""

    def __init__(
        self,
        log: list[str],
        cards_by_status: dict[TicketStatus, list[Ticket]] | None = None,
    ) -> None:
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
        self.log.append(f"set_status:{status.value}")
        for tickets in self.cards_by_status.values():
            if ticket in tickets:
                tickets.remove(ticket)
        self.cards_by_status[status].append(ticket)


class FakeCodeAgent:
    """Scripted code agent: replays queued review verdicts and records calls.

    Review calls pop the next verdict of their queue, so tests spell out the
    full sequence of attempts.

    Attributes:
        implemented_with: Feedback received by each implement call, in order.
    """

    def __init__(
        self,
        log: list[str],
        quality_verdicts: list[StageOutcome],
        final_verdicts: list[StageOutcome],
    ) -> None:
        self.log = log
        self.quality_verdicts = quality_verdicts
        self.final_verdicts = final_verdicts
        self.implemented_with: list[tuple[str, ...]] = []

    def implement(self, ticket: Ticket, feedback: tuple[str, ...]) -> None:
        self.log.append("implement")
        self.implemented_with.append(feedback)

    def quality_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        self.log.append("quality_review")
        return self.quality_verdicts.pop(0)

    def final_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        self.log.append("final_review")
        return self.final_verdicts.pop(0)


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
    ) -> None:
        self.log = log
        self.pull_request_url = pull_request_url
        self.created_branches: list[str] = []
        self.published: list[tuple[str, str, str]] = []
        self.states_by_branch = dict(states_by_branch or {})
        self.default_state = default_state

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
