"""Stage outcome value object: the result an agent reports for its stage."""

from dataclasses import dataclass

from ai_factory.domain.errors import InvalidStageOutcomeError


@dataclass(frozen=True)
class StageOutcome:
    """Result of one pipeline stage, as reported by the responsible agent.

    Attributes:
        approved: Whether the agent approves moving to the next stage.
        summary: Human-readable summary of the verdict (must not be blank).
        findings: Specific issues found by the agent, if any.
    """

    approved: bool
    summary: str
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise InvalidStageOutcomeError("summary must not be blank")
