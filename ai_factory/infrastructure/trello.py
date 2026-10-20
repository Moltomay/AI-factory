"""Trello adapter: ticket source backed by a Trello list."""

from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure.http import HTTP_TIMEOUT_SECONDS, JsonHttpClient

API_BASE_URL = "https://api.trello.com/1"
CARD_FIELDS = "id,name,desc"


class TrelloBoard:
    """Ticket source backed by a Trello list.

    Reads the first card of the configured list as the next ticket and posts
    processing results as comments on the ticket's card. The API key and token
    travel as query parameters, so they must never appear in error messages.
    """

    def __init__(
        self,
        api_key: str,
        token: str,
        list_id: str,
        base_url: str = API_BASE_URL,
        timeout_seconds: int = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the adapter.

        Args:
            api_key: Trello API key (from the Power-Up admin portal).
            token: Trello user token granted to that API key.
            list_id: Id of the list holding the tickets to process.
            base_url: API root, overridable for tests.
            timeout_seconds: HTTP timeout for every call.
        """
        self._api_key = api_key
        self._token = token
        self._list_id = list_id
        self._client = JsonHttpClient(base_url, timeout_seconds)

    def fetch_next_ticket(self) -> Ticket | None:
        """Return the first card of the configured list as a ticket, if any."""
        cards = self._client.request_json(
            "GET",
            f"/lists/{self._list_id}/cards",
            {**self._auth_params(), "fields": CARD_FIELDS},
        )
        if not cards:
            return None
        card = cards[0]
        return Ticket(ticket_id=card["id"], title=card["name"], description=card["desc"])

    def report_result(self, ticket: Ticket, message: str) -> None:
        """Comment the processing result on the ticket's card."""
        self._client.request_json(
            "POST",
            f"/cards/{ticket.ticket_id}/actions/comments",
            {**self._auth_params(), "text": message},
        )

    def _auth_params(self) -> dict[str, str]:
        return {"key": self._api_key, "token": self._token}
