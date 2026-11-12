"""Structured review findings: the contract shared by the two reviewer agents.

The severities, categories and the cap are business rules, so they live in the
domain layer. The OpenRouter adapter only maps the verdict JSON onto these
objects and never decides what blocks.
"""

from dataclasses import dataclass
from enum import Enum

from ai_factory.domain.errors import InvalidFindingError

MAX_FINDINGS = 20


class FindingSeverity(Enum):
    """How hard a finding blocks the pipeline."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


SEVERITY_ORDER = {
    FindingSeverity.BLOCKER: 0,
    FindingSeverity.MAJOR: 1,
    FindingSeverity.MINOR: 2,
}


class FindingCategory(Enum):
    """What the finding is about; mirrors the two reviewer mandates."""

    SPEC_CONFORMANCE = "spec_conformance"
    TESTS = "tests"
    SECURITY = "security"
    DESIGN = "design"
    ERROR_HANDLING = "error_handling"
    SCOPE = "scope"
    OPERABILITY = "operability"
    OTHER = "other"


class FindingStatus(Enum):
    """Whether the reviewer managed to prove the finding."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Finding:
    """One issue reported by a reviewer.

    Attributes:
        severity: How hard the finding blocks the pipeline.
        category: Mandate area the finding belongs to.
        location: `path:line` when it points at code, otherwise a scope name.
        message: What is wrong, in one actionable sentence.
        status: Whether the reviewer proved the finding.
        evidence: Diff excerpt, command output or observation. Required when
            `status` is VERIFIED; empty is allowed only for UNVERIFIED.
        ac: Acceptance criterion the finding relates to, when the ticket has any.
    """

    severity: FindingSeverity
    category: FindingCategory
    location: str
    message: str
    status: FindingStatus
    evidence: str = ""
    ac: str | None = None

    def __post_init__(self) -> None:
        self._require_enum("severity", self.severity, FindingSeverity)
        self._require_enum("category", self.category, FindingCategory)
        self._require_enum("status", self.status, FindingStatus)
        if not self.location.strip():
            raise InvalidFindingError("location must not be blank")
        if not self.message.strip():
            raise InvalidFindingError("message must not be blank")
        if self.status is FindingStatus.VERIFIED and not self.evidence.strip():
            raise InvalidFindingError("a verified finding requires evidence")
        if self.ac is not None and not isinstance(self.ac, str):
            raise InvalidFindingError("ac must be a string when present")
        if self.ac is not None and not self.ac.strip():
            object.__setattr__(self, "ac", None)

    @property
    def is_blocking(self) -> bool:
        """Whether this finding blocks the pipeline."""
        return self.severity in (FindingSeverity.BLOCKER, FindingSeverity.MAJOR)

    def _require_enum(self, name: str, value: object, enum_type: type[Enum]) -> None:
        if not isinstance(value, enum_type):
            raise InvalidFindingError(f"{name} must be a {enum_type.__name__}")
