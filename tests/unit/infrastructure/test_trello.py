"""Behavior tests for the Trello adapter, with a stubbed HTTPS client (no network)."""

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure.http import JsonHttpClient
from ai_factory.infrastructure.trello import TrelloBoard


def _make_board() -> TrelloBoard:
    return TrelloBoard("test-api-key", "test-secret-token", "list-1")


def _stub_request_json(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object]
) -> list[tuple[str, str, dict[str, str]]]:
    calls: list[tuple[str, str, dict[str, str]]] = []
    queue = list(outcomes)

    def fake_request_json(
        self: JsonHttpClient,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        calls.append((method, path, dict(params or {})))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(JsonHttpClient, "request_json", fake_request_json)
    return calls


def test_ac1_fetch_next_ticket_maps_first_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: the first card of the list becomes a Ticket."""
    cards = [
        {"id": "card-1", "name": "Add hello.txt", "desc": "Create the file."},
        {"id": "card-2", "name": "Second card", "desc": ""},
    ]
    calls = _stub_request_json(monkeypatch, [cards])

    ticket = _make_board().fetch_next_ticket()

    assert ticket == Ticket(
        ticket_id="card-1", title="Add hello.txt", description="Create the file."
    )
    assert calls == [
        (
            "GET",
            "/lists/list-1/cards",
            {"key": "test-api-key", "token": "test-secret-token", "fields": "id,name,desc"},
        )
    ]


def test_ac1_empty_list_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: an empty list means no ticket to process."""
    _stub_request_json(monkeypatch, [[]])

    assert _make_board().fetch_next_ticket() is None


def test_ac2_report_result_posts_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: the result is posted as a comment on the ticket's card."""
    calls = _stub_request_json(monkeypatch, [{"id": "comment-1"}])
    ticket = Ticket(ticket_id="card-1", title="Add hello.txt", description="")

    _make_board().report_result(ticket, "Pull request opened: url")

    assert calls == [
        (
            "POST",
            "/cards/card-1/actions/comments",
            {
                "key": "test-api-key",
                "token": "test-secret-token",
                "text": "Pull request opened: url",
            },
        )
    ]


def test_ac2_service_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: transport failures surface as ExternalServiceError."""
    _stub_request_json(monkeypatch, [ExternalServiceError("HTTP 401 for GET /lists/list-1/cards")])

    with pytest.raises(ExternalServiceError):
        _make_board().fetch_next_ticket()
