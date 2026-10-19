"""Process-ticket use case: run one ticket through the whole agent pipeline."""

from dataclasses import dataclass

from ai_factory.application.ports import CodeAgent, QualityRunner, TicketSource, VersionControl
from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.pipeline import PipelineRun, PipelineStage
from ai_factory.domain.quality_gate import combine_quality_results
from ai_factory.domain.ticket import Ticket

BRANCH_NAME_TEMPLATE = "factory/{ticket_id}"
PULL_REQUEST_OPENED_MESSAGE_TEMPLATE = "Pull request opened: {url}"
FAILED_MESSAGE_TEMPLATE = "Automated processing failed: {reason}"


@dataclass(frozen=True)
class ProcessTicketResult:
    """Outcome of one ticket processing run.

    Attributes:
        run: Final state of the pipeline run (terminal stage, attempts, failure reason).
        pull_request_url: URL of the opened pull request; None when the run failed.
    """

    run: PipelineRun
    pull_request_url: str | None


class ProcessTicket:
    """Process one ticket end to end: implement, quality gate, review, pull request.

    Orchestrates the domain pipeline state machine and depends only on the
    application ports for the outside world (see ARCHITECTURE.md).
    """

    def __init__(
        self,
        ticket_source: TicketSource,
        code_agent: CodeAgent,
        quality_runner: QualityRunner,
        version_control: VersionControl,
    ) -> None:
        """Wire the use case to its ports.

        Args:
            ticket_source: Where the final result is reported.
            code_agent: Agent implementing the change and reviewing it.
            quality_runner: Runner for the deterministic checks.
            version_control: Git operations publishing the pull request.
        """
        self._ticket_source = ticket_source
        self._code_agent = code_agent
        self._quality_runner = quality_runner
        self._version_control = version_control

    def execute(self, ticket: Ticket) -> ProcessTicketResult:
        """Run the ticket through the pipeline until it reaches a terminal stage.

        Args:
            ticket: The ticket to process.

        Returns:
            The final pipeline state and the pull request URL when one was opened.
        """
        run = PipelineRun(ticket)
        run.start()
        branch_name = BRANCH_NAME_TEMPLATE.format(ticket_id=ticket.ticket_id)
        self._version_control.create_branch(branch_name)
        feedback: tuple[str, ...] = ()
        while not run.is_finished:
            feedback = self._advance(run, feedback)
        pull_request_url = self._finish(run, branch_name)
        return ProcessTicketResult(run=run, pull_request_url=pull_request_url)

    def _advance(self, run: PipelineRun, feedback: tuple[str, ...]) -> tuple[str, ...]:
        """Execute the run's current stage and apply its transition.

        Args:
            run: Run sitting in a non-terminal stage.
            feedback: Findings from the previous failed attempt; empty on the first attempt.

        Returns:
            Feedback to hand to the next development attempt.

        Raises:
            InvalidStageTransitionError: If the run sits in a stage this use case
                cannot drive, which would otherwise loop forever.
        """
        if run.stage is PipelineStage.IMPLEMENTING:
            self._code_agent.implement(run.ticket, feedback)
            run.development_completed()
            return feedback
        if run.stage is PipelineStage.QUALITY_CHECK:
            verdict = combine_quality_results(
                self._quality_runner.run_checks(),
                self._code_agent.quality_review(run.ticket, feedback),
            )
            run.record_quality_outcome(verdict.approved)
            return verdict.findings
        if run.stage is PipelineStage.FINAL_REVIEW:
            verdict = self._code_agent.final_review(run.ticket, feedback)
            run.record_review_outcome(verdict.approved)
            return verdict.findings
        raise InvalidStageTransitionError(f"cannot advance pipeline from stage {run.stage.name}")

    def _finish(self, run: PipelineRun, branch_name: str) -> str | None:
        """Publish the pull request or report the failure, then notify the tracker.

        Args:
            run: Run sitting in a terminal stage.
            branch_name: Working branch created for the ticket.

        Returns:
            The pull request URL, or None when the run failed.
        """
        if run.stage is PipelineStage.PULL_REQUEST_OPENED:
            pull_request_url = self._version_control.publish_pull_request(
                branch_name, run.ticket.title, run.ticket.description
            )
            self._ticket_source.report_result(
                run.ticket,
                PULL_REQUEST_OPENED_MESSAGE_TEMPLATE.format(url=pull_request_url),
            )
            return pull_request_url
        self._ticket_source.report_result(
            run.ticket, FAILED_MESSAGE_TEMPLATE.format(reason=run.failure_reason)
        )
        return None
