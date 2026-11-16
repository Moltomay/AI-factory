"""Domain exceptions.

Raised by the domain model when an entity is invalid or a pipeline
transition is attempted from the wrong state. Infrastructure adapters
must translate low-level errors into domain errors at the boundary
(see ARCHITECTURE.md).
"""


class DomainError(Exception):
    """Base class for all domain errors."""


class InvalidTicketError(DomainError):
    """Raised when a Ticket is built with missing or blank required fields."""


class InvalidFindingError(DomainError):
    """Raised when a Finding has a blank field, a missing proof or an unknown value."""


class InvalidStageOutcomeError(DomainError):
    """Raised when a StageOutcome is built with a blank summary."""


class InvalidStageTransitionError(DomainError):
    """Raised when a pipeline method is called from the wrong stage."""


class InvalidSpecificationError(DomainError):
    """Raised when a specification artifact is malformed, out of bounds or untraceable."""


class ExternalServiceError(DomainError):
    """Raised by adapters when an external service call fails."""
