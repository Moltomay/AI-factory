"""Stage outcome value object: the result an agent reports for its stage."""

from dataclasses import dataclass, field

from ai_factory.domain.errors import InvalidStageOutcomeError
from ai_factory.domain.findings import MAX_FINDINGS, SEVERITY_ORDER, Finding


@dataclass(frozen=True)
class ReviewFeedback:
    """What the developer is told to fix after a rejected stage.

    Attributes:
        findings: Findings that caused the rejection, ordered by severity.
        omitted_findings: How many findings the cap dropped.
    """

    findings: tuple[Finding, ...] = ()
    omitted_findings: int = 0


@dataclass(frozen=True)
class StageOutcome:
    """Result of one pipeline stage, as reported by the responsible agent.

    Severity ordering and the finding cap are applied at construction, so the
    object always carries at most MAX_FINDINGS findings, blockers first.

    Attributes:
        summary: Human-readable summary of the verdict (must not be blank).
        findings: Review findings, sorted by severity.
        omitted_findings: How many findings the cap dropped.
    """

    summary: str
    findings: tuple[Finding, ...] = ()
    # No default on purpose: __post_init__ always computes it, so a default
    # would be dead code that only the mutation probe can observe.
    omitted_findings: int = field(init=False)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise InvalidStageOutcomeError("summary must not be blank")
        ordered = sorted(self.findings, key=lambda finding: SEVERITY_ORDER[finding.severity])
        object.__setattr__(self, "findings", tuple(ordered[:MAX_FINDINGS]))
        object.__setattr__(self, "omitted_findings", max(0, len(ordered) - MAX_FINDINGS))

    @property
    def approved(self) -> bool:
        """Whether the stage approves the change: no blocker and no major."""
        return not any(finding.is_blocking for finding in self.findings)

    @property
    def feedback(self) -> ReviewFeedback:
        """The actionable feedback to hand to the next development attempt."""
        return ReviewFeedback(findings=self.findings, omitted_findings=self.omitted_findings)
