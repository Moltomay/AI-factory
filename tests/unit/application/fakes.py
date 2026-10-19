"""In-memory fake ports for the application use case tests (no network, no git)."""

from ai_factory.domain.outcomes import StageOutcome
from ai_factory.domain.ticket import Ticket


class FakeTicketSource:
    """Ticket source recording every reported result."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.reported: list[tuple[Ticket, str]] = []

    def report_result(self, ticket: Ticket, message: str) -> None:
        self.log.append("report_result")
        self.reported.append((ticket, message))


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

    def __init__(self, log: list[str], pull_request_url: str = "https://example.test/pr/1") -> None:
        self.log = log
        self.pull_request_url = pull_request_url
        self.created_branches: list[str] = []
        self.published: list[tuple[str, str, str]] = []

    def create_branch(self, branch_name: str) -> None:
        self.log.append(f"create_branch:{branch_name}")
        self.created_branches.append(branch_name)

    def publish_pull_request(self, branch_name: str, title: str, body: str) -> str:
        self.log.append("publish_pull_request")
        self.published.append((branch_name, title, body))
        return self.pull_request_url
