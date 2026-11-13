"""Process-ticket use case: run one ticket through the whole agent pipeline."""

from dataclasses import dataclass
from typing import NamedTuple

from ai_factory.application.ports import (
    CodeAgent,
    QualityRunner,
    SpecAgent,
    TicketSource,
    TicketStatus,
    VersionControl,
)
from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.findings import Finding, FindingSeverity
from ai_factory.domain.outcomes import ReviewFeedback, StageOutcome
from ai_factory.domain.pipeline import PipelineRun, PipelineStage
from ai_factory.domain.quality_gate import failed_checks_outcome
from ai_factory.domain.specification import Specification
from ai_factory.domain.ticket import Ticket

BRANCH_NAME_TEMPLATE = "factory/{ticket_id}"
PULL_REQUEST_OPENED_MESSAGE_TEMPLATE = "Pull request opened: {url}"
FAILED_MESSAGE_TEMPLATE = "Automated processing failed: {reason}"
ACCEPTANCE_CRITERIA_SECTION_HEADER = "## Acceptance criteria"
ACCEPTANCE_CRITERIA_LINE_TEMPLATE = "- {criterion_id}: {statement}"
REVIEW_SECTION_HEADER = "## Automated review"
REVIEW_SECTION_INTRO = "Non-blocking findings from the automated review:"
AC_SUFFIX_TEMPLATE = " ({ac})"
EVIDENCE_SUFFIX_TEMPLATE = " — evidence: {evidence}"


@dataclass(frozen=True)
class ProcessTicketResult:
    """Outcome of one ticket processing run.

    Attributes:
        run: Final state of the pipeline run (terminal stage, attempts, failure reason).
        pull_request_url: URL of the opened pull request; None when the run failed.
    """

    run: PipelineRun
    pull_request_url: str | None


class _StageResult(NamedTuple):
    """What one stage hands over: retry feedback and its non-blocking findings."""

    feedback: ReviewFeedback
    minors: tuple[Finding, ...]


class ProcessTicket:
    """Process one ticket end to end: implement, quality gate, review, pull request.

    Orchestrates the domain pipeline state machine and depends only on the
    application ports for the outside world (see ARCHITECTURE.md).
    """

    def __init__(
        self,
        ticket_source: TicketSource,
        spec_agent: SpecAgent,
        code_agent: CodeAgent,
        quality_runner: QualityRunner,
        version_control: VersionControl,
    ) -> None:
        """Wire the use case to its ports.

        Args:
            ticket_source: Where the final result is reported.
            spec_agent: Agent turning the ticket into a validated specification.
            code_agent: Agent implementing the change and reviewing it.
            quality_runner: Runner for the deterministic checks.
            version_control: Git operations publishing the pull request.
        """
        self._ticket_source = ticket_source
        self._spec_agent = spec_agent
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
        specification = self._specify(run)
        if specification is None:
            self._report_failure(run)
            return ProcessTicketResult(run=run, pull_request_url=None)
        branch_name = BRANCH_NAME_TEMPLATE.format(ticket_id=ticket.ticket_id)
        self._version_control.create_branch(branch_name)
        feedback = ReviewFeedback()
        minor_findings: list[Finding] = []
        while not run.is_finished:
            step = self._advance(run, specification, feedback)
            feedback = step.feedback
            if run.stage is PipelineStage.IMPLEMENTING:
                minor_findings = []
            else:
                minor_findings.extend(step.minors)
        pull_request_url = self._finish(run, branch_name, specification, tuple(minor_findings))
        return ProcessTicketResult(run=run, pull_request_url=pull_request_url)

    def _specify(self, run: PipelineRun) -> Specification | None:
        """Run the Spec stage and move the run forward when the ticket is clear.

        Args:
            run: Run sitting in the SPECIFYING stage.

        Returns:
            The validated specification, or None when clarification is required.

        Raises:
            InvalidStageTransitionError: If the run is not in the SPECIFYING stage.
        """
        if run.stage is not PipelineStage.SPECIFYING:
            raise InvalidStageTransitionError(f"cannot specify from stage {run.stage.name}")
        outcome = self._spec_agent.specify(run.ticket)
        if outcome.specification is None:
            run.clarification_requested(outcome.questions)
            return None
        run.specification_completed(outcome.specification)
        return outcome.specification

    def _advance(
        self, run: PipelineRun, specification: Specification, feedback: ReviewFeedback
    ) -> _StageResult:
        """Execute the run's current stage and apply its transition.

        Args:
            run: Run sitting in a non-terminal stage.
            specification: Validated specification both agents work against.
            feedback: Findings from the previous failed attempt; empty on the first attempt.

        Returns:
            The feedback to hand to the next development attempt and the
            non-blocking findings reported by this stage.

        Raises:
            InvalidStageTransitionError: If the run sits in a stage this use case
                cannot drive, which would otherwise loop forever.
        """
        if run.stage is PipelineStage.IMPLEMENTING:
            self._code_agent.implement(run.ticket, specification, feedback)
            run.development_completed()
            return _StageResult(feedback=feedback, minors=())
        if run.stage is PipelineStage.REVIEW:
            verdict = self._review_verdict(run.ticket, specification, feedback)
            run.record_review_outcome(verdict.approved)
            return _StageResult(feedback=verdict.feedback, minors=_minors(verdict.findings))
        raise InvalidStageTransitionError(f"cannot advance pipeline from stage {run.stage.name}")

    def _review_verdict(
        self, ticket: Ticket, specification: Specification, feedback: ReviewFeedback
    ) -> StageOutcome:
        """Run the deterministic gate first, then review a green build.

        Args:
            ticket: The ticket being processed.
            specification: Validated specification both agents work against.
            feedback: Findings from the previous failed attempt.

        Returns:
            The deterministic outcome when the gate is red, otherwise the
            reviewer verdict.
        """
        if not self._quality_runner.run_checks():
            return failed_checks_outcome()
        return self._code_agent.review(ticket, specification, feedback)

    def _finish(
        self,
        run: PipelineRun,
        branch_name: str,
        specification: Specification,
        minors: tuple[Finding, ...],
    ) -> str | None:
        """Publish the pull request or report the failure, then notify the tracker.

        Args:
            run: Run sitting in a terminal stage.
            branch_name: Working branch created for the ticket.
            specification: Validated specification both agents worked against.
            minors: Non-blocking findings to surface in the pull request body.

        Returns:
            The pull request URL, or None when the run failed.
        """
        if run.stage is PipelineStage.PULL_REQUEST_OPENED:
            pull_request_url = self._version_control.publish_pull_request(
                branch_name,
                run.ticket.title,
                _build_pull_request_body(run.ticket.description, specification, minors),
            )
            self._ticket_source.set_status(run.ticket, TicketStatus.IN_REVIEW)
            self._ticket_source.report_result(
                run.ticket,
                PULL_REQUEST_OPENED_MESSAGE_TEMPLATE.format(url=pull_request_url),
            )
            return pull_request_url
        self._report_failure(run)
        return None

    def _report_failure(self, run: PipelineRun) -> None:
        """Report the terminal failure reason on the ticket."""
        self._ticket_source.report_result(
            run.ticket, FAILED_MESSAGE_TEMPLATE.format(reason=run.failure_reason)
        )


def _minors(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Return the non-blocking findings of a verdict."""
    return tuple(finding for finding in findings if finding.severity is FindingSeverity.MINOR)


def _build_pull_request_body(
    description: str,
    specification: Specification | None,
    minors: tuple[Finding, ...],
) -> str:
    """Append the acceptance criteria and the non-blocking findings to the description.

    Args:
        description: Pull request body requested by the ticket.
        specification: Validated specification, or None when the run has none.
        minors: Non-blocking findings reported by the approved verdicts.

    Returns:
        The non-empty sections joined in a stable order: ticket description,
        acceptance criteria, automated review.
    """
    sections: list[str] = []
    if description.strip():
        sections.append(description)
    if specification is not None:
        sections.append(_render_acceptance_criteria(specification))
    if minors:
        sections.append(_render_review_section(minors))
    return "\n\n".join(sections)


def _render_acceptance_criteria(specification: Specification) -> str:
    """Render the acceptance criteria section, without the ticket quotes."""
    lines = [ACCEPTANCE_CRITERIA_SECTION_HEADER, ""]
    lines.extend(
        ACCEPTANCE_CRITERIA_LINE_TEMPLATE.format(
            criterion_id=criterion.id, statement=criterion.statement
        )
        for criterion in specification.acceptance_criteria
    )
    return "\n".join(lines)


def _render_review_section(minors: tuple[Finding, ...]) -> str:
    """Render the automated review section for the non-blocking findings."""
    lines = [REVIEW_SECTION_HEADER, "", REVIEW_SECTION_INTRO, ""]
    lines.extend(_render_minor_finding(finding) for finding in minors)
    return "\n".join(lines)


def _render_minor_finding(finding: Finding) -> str:
    """Render one non-blocking finding as a Markdown list item."""
    line = f"- [{finding.category.value}] {finding.location} — {finding.message}"
    if finding.ac:
        line += AC_SUFFIX_TEMPLATE.format(ac=finding.ac)
    if finding.evidence:
        line += EVIDENCE_SUFFIX_TEMPLATE.format(evidence=finding.evidence)
    return line
