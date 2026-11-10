"""Trello adapter: ticket source backed by the lifecycle lists of one board."""

from dataclasses import dataclass

from ai_factory.application.ports import TicketStatus
from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure.http import HTTP_TIMEOUT_SECONDS, JsonHttpClient

API_BASE_URL = "https://api.trello.com/1"
CARD_FIELDS = "id,name,desc"


@dataclass(frozen=True)
class TrelloLists:
    """Identifiers of the three lists that drive the ticket lifecycle."""

    todo: str
    in_review: str
    done: str

    def for_status(self, status: TicketStatus) -> str:
        """Return the list identifier matching the given status."""
        lists = {
            TicketStatus.TODO: self.todo,
            TicketStatus.IN_REVIEW: self.in_review,
            TicketStatus.DONE: self.done,
        }
        return lists[status]


class TrelloBoard:
    """Ticket source backed by the three lifecycle lists of a Trello board.

    Reads the first card of the To Do list as the next ticket, moves cards
    between the configured lists, and posts processing results as comments. The
    API key and token travel as query parameters, so they must never appear in
    error messages.
    """

    def __init__(
        self,
        api_key: str,
        token: str,
        lists: TrelloLists,
        base_url: str = API_BASE_URL,
        timeout_seconds: int = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the adapter.

        Args:
            api_key: Trello API key (from the Power-Up admin portal).
            token: Trello user token granted to that API key.
            lists: Identifiers of the To Do, In Review and Done lists.
            base_url: API root, overridable for tests.
            timeout_seconds: HTTP timeout for every call.
        """
        self._api_key = api_key
        self._token = token
        self._lists = lists
        self._client = JsonHttpClient(base_url, timeout_seconds)

    def fetch_next_ticket(self) -> Ticket | None:
        """Return the first card of the To Do list as a ticket, if any."""
        cards = self._client.request_json(
            "GET",
            f"/lists/{self._lists.todo}/cards",
            {**self._auth_params(), "fields": CARD_FIELDS},
        )
        if not cards:
            return None
        return _to_ticket(cards[0])

    def report_result(self, ticket: Ticket, message: str) -> None:
        """Comment the processing result on the ticket's card."""
        self._client.request_json(
            "POST",
            f"/cards/{ticket.ticket_id}/actions/comments",
            {**self._auth_params(), "text": message},
        )

    def list_by_status(self, status: TicketStatus) -> list[Ticket]:
        """Return the cards of the list matching the status."""
        cards = self._client.request_json(
            "GET",
            f"/lists/{self._lists.for_status(status)}/cards",
            {**self._auth_params(), "fields": CARD_FIELDS},
        )
        return [_to_ticket(card) for card in cards]

    def set_status(self, ticket: Ticket, status: TicketStatus) -> None:
        """Move the ticket's card to the list matching the status."""
        self._client.request_json(
            "PUT",
            f"/cards/{ticket.ticket_id}",
            {**self._auth_params(), "idList": self._lists.for_status(status)},
        )

    def _auth_params(self) -> dict[str, str]:
        return {"key": self._api_key, "token": self._token}


def _to_ticket(card: dict[str, str]) -> Ticket:
    """Map one Trello card payload to the domain ticket."""
    return Ticket(ticket_id=card["id"], title=card["name"], description=card["desc"])
