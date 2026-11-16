"""Pipeline state machine: legal stages, transitions and the retry budget."""

from dataclasses import dataclass
from enum import Enum

from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.specification import Specification
from ai_factory.domain.ticket import Ticket

MAX_DEVELOPMENT_ATTEMPTS = 3
FAILED_REASON_TEMPLATE = "Development retry budget exhausted after {attempts} attempts"
CLARIFICATION_REASON_TEMPLATE = "Ticket needs clarification: {questions}"
CLARIFICATION_QUESTION_SEPARATOR = " | "


class AgentRole(Enum):
    """Agent responsible for one stage of the pipeline."""

    SPEC_WRITER = "spec_writer"
    DEVELOPER = "developer"
    CODE_REVIEWER = "code_reviewer"


class PipelineStage(Enum):
    """Stages a ticket goes through in the MVP pipeline."""

    NEW = "new"
    SPECIFYING = "specifying"
    IMPLEMENTING = "implementing"
    REVIEW = "review"
    PULL_REQUEST_OPENED = "pull_request_opened"
    FAILED = "failed"

    @property
    def role(self) -> AgentRole | None:
        """Return the agent responsible for this stage, if any."""
        return _STAGE_ROLES.get(self)


_STAGE_ROLES = {
    PipelineStage.SPECIFYING: AgentRole.SPEC_WRITER,
    PipelineStage.IMPLEMENTING: AgentRole.DEVELOPER,
    PipelineStage.REVIEW: AgentRole.CODE_REVIEWER,
}


@dataclass
class PipelineRun:
    """Mutable state of one ticket's progression through the pipeline.

    Attributes:
        ticket: The ticket being processed.
        stage: Current pipeline stage.
        development_attempts: Number of development runs started so far
            (the initial attempt counts as 1 once the specification is ready).
        failure_reason: Why the run failed; set only in the FAILED stage.
        specification: Validated specification shared with the Coding and Code
            Review agents; None until the Spec stage completes.
    """

    ticket: Ticket
    stage: PipelineStage = PipelineStage.NEW
    development_attempts: int = 0
    failure_reason: str | None = None
    specification: Specification | None = None

    @property
    def is_finished(self) -> bool:
        """Whether the run reached a terminal stage (PR opened or failed)."""
        return self.stage in (PipelineStage.PULL_REQUEST_OPENED, PipelineStage.FAILED)

    def start(self) -> None:
        """Move from NEW to SPECIFYING, before any code is written."""
        self._require_stage(PipelineStage.NEW, "start")
        self.stage = PipelineStage.SPECIFYING
        self.development_attempts = 0

    def specification_completed(self, specification: Specification) -> None:
        """Move from SPECIFYING to IMPLEMENTING once the specification is validated.

        Args:
            specification: Validated specification the agents must work against.
        """
        self._require_stage(PipelineStage.SPECIFYING, "specification_completed")
        self.specification = specification
        self.stage = PipelineStage.IMPLEMENTING
        self.development_attempts = 1

    def clarification_requested(self, questions: tuple[str, ...]) -> None:
        """Fail the run when the ticket cannot be specified without invention.

        Args:
            questions: Actionable questions reported on the ticket.
        """
        self._require_stage(PipelineStage.SPECIFYING, "clarification_requested")
        formatted_questions = CLARIFICATION_QUESTION_SEPARATOR.join(questions)
        self.failure_reason = CLARIFICATION_REASON_TEMPLATE.format(questions=formatted_questions)
        self.stage = PipelineStage.FAILED

    def development_completed(self) -> None:
        """Move from IMPLEMENTING to REVIEW once the developer is done."""
        self._require_stage(PipelineStage.IMPLEMENTING, "development_completed")
        self.stage = PipelineStage.REVIEW

    def record_review_outcome(self, approved: bool) -> None:
        """Apply the review verdict: open the PR, retry, or fail.

        Args:
            approved: Whether the deterministic gate and the reviewer approved
                the change.
        """
        self._require_stage(PipelineStage.REVIEW, "record_review_outcome")
        if approved:
            self.stage = PipelineStage.PULL_REQUEST_OPENED
            return
        self._retry_or_fail()

    def _retry_or_fail(self) -> None:
        if self.development_attempts < MAX_DEVELOPMENT_ATTEMPTS:
            self.development_attempts += 1
            self.stage = PipelineStage.IMPLEMENTING
            return
        self.failure_reason = FAILED_REASON_TEMPLATE.format(attempts=self.development_attempts)
        self.stage = PipelineStage.FAILED

    def _require_stage(self, expected: PipelineStage, method_name: str) -> None:
        if self.stage is not expected:
            raise InvalidStageTransitionError(
                f"{method_name} requires stage {expected.name}, current stage is {self.stage.name}"
            )
