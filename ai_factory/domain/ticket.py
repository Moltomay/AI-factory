"""Ticket entity: the unit of work the factory processes."""

from dataclasses import dataclass

from ai_factory.domain.errors import InvalidTicketError


@dataclass(frozen=True)
class Ticket:
    """A work item picked up from the tracker.

    Attributes:
        ticket_id: Tracker identifier of the ticket (must not be blank).
        title: Short description of the requested change (must not be blank).
        description: Full ticket body as written by the requester.
    """

    ticket_id: str
    title: str
    description: str

    def __post_init__(self) -> None:
        if not self.ticket_id.strip():
            raise InvalidTicketError("ticket_id must not be blank")
        if not self.title.strip():
            raise InvalidTicketError("title must not be blank")
