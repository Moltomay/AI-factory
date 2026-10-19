"""Pipeline state machine: legal stages, transitions and the retry budget."""

from dataclasses import dataclass
from enum import Enum

from ai_factory.domain.errors import InvalidStageTransitionError
from ai_factory.domain.ticket import Ticket

MAX_DEVELOPMENT_ATTEMPTS = 3
FAILED_REASON_TEMPLATE = "Development retry budget exhausted after {attempts} attempts"


class AgentRole(Enum):
    """Agent responsible for one stage of the pipeline."""

    DEVELOPER = "developer"
    QUALITY_ANALYST = "quality_analyst"
    REVIEWER = "reviewer"


class PipelineStage(Enum):
    """Stages a ticket goes through in the MVP pipeline."""

    NEW = "new"
    IMPLEMENTING = "implementing"
    QUALITY_CHECK = "quality_check"
    FINAL_REVIEW = "final_review"
    PULL_REQUEST_OPENED = "pull_request_opened"
    FAILED = "failed"

    @property
    def role(self) -> AgentRole | None:
        """Return the agent responsible for this stage, if any."""
        return _STAGE_ROLES.get(self)


_STAGE_ROLES = {
    PipelineStage.IMPLEMENTING: AgentRole.DEVELOPER,
    PipelineStage.QUALITY_CHECK: AgentRole.QUALITY_ANALYST,
    PipelineStage.FINAL_REVIEW: AgentRole.REVIEWER,
}


@dataclass
class PipelineRun:
    """Mutable state of one ticket's progression through the pipeline.

    Attributes:
        ticket: The ticket being processed.
        stage: Current pipeline stage.
        development_attempts: Number of development runs started so far
            (the initial attempt counts as 1 once the run has started).
        failure_reason: Why the run failed; set only in the FAILED stage.
    """

    ticket: Ticket
    stage: PipelineStage = PipelineStage.NEW
    development_attempts: int = 0
    failure_reason: str | None = None

    @property
    def is_finished(self) -> bool:
        """Whether the run reached a terminal stage (PR opened or failed)."""
        return self.stage in (PipelineStage.PULL_REQUEST_OPENED, PipelineStage.FAILED)

    def start(self) -> None:
        """Move from NEW to IMPLEMENTING, starting the first development attempt."""
        self._require_stage(PipelineStage.NEW, "start")
        self.stage = PipelineStage.IMPLEMENTING
        self.development_attempts = 1

    def development_completed(self) -> None:
        """Move from IMPLEMENTING to QUALITY_CHECK once the developer is done."""
        self._require_stage(PipelineStage.IMPLEMENTING, "development_completed")
        self.stage = PipelineStage.QUALITY_CHECK

    def record_quality_outcome(self, approved: bool) -> None:
        """Apply the QA verdict: move to FINAL_REVIEW, retry, or fail.

        Args:
            approved: Whether the QA gate approved the change.
        """
        self._require_stage(PipelineStage.QUALITY_CHECK, "record_quality_outcome")
        if approved:
            self.stage = PipelineStage.FINAL_REVIEW
            return
        self._retry_or_fail()

    def record_review_outcome(self, approved: bool) -> None:
        """Apply the reviewer verdict: open the PR, retry, or fail.

        Args:
            approved: Whether the final review approved the change.
        """
        self._require_stage(PipelineStage.FINAL_REVIEW, "record_review_outcome")
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
