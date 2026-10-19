"""AC1: Ticket entity invariants."""

import pytest

from ai_factory.domain.errors import InvalidTicketError
from ai_factory.domain.ticket import Ticket


def test_ac1_ticket_accepts_valid_fields() -> None:
    """AC1: a ticket with non-blank identifiers is accepted."""
    ticket = Ticket(ticket_id="card-123", title="Add the feature", description="Full body")
    assert ticket.ticket_id == "card-123"
    assert ticket.title == "Add the feature"
    assert ticket.description == "Full body"


@pytest.mark.parametrize(
    ("ticket_id", "title"),
    [("", "Title"), ("   ", "Title"), ("card-1", ""), ("card-1", "   ")],
)
def test_ac1_blank_required_fields_are_rejected(ticket_id: str, title: str) -> None:
    """AC1: blank ticket_id or title raises InvalidTicketError."""
    with pytest.raises(InvalidTicketError):
        Ticket(ticket_id=ticket_id, title=title, description="Full body")
