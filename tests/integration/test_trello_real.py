"""Real Trello integration test: runs only with local credentials present (AC8)."""

import json
import os
import urllib.parse
import urllib.request
import uuid

import pytest

from ai_factory.infrastructure.trello import TrelloBoard

pytestmark = pytest.mark.integration

_REQUIRED_ENV = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_LIST_ID")
HTTP_TIMEOUT_SECONDS = 20


@pytest.mark.skipif(
    any(not os.environ.get(name) for name in _REQUIRED_ENV),
    reason="Trello credentials missing from the environment",
)
def test_ac8_real_fetch_and_comment_round_trip() -> None:
    """AC8: fetch the sandbox card and post a verifiable comment on it."""
    board = TrelloBoard(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_TOKEN"],
        list_id=os.environ["TRELLO_LIST_ID"],
    )

    ticket = board.fetch_next_ticket()

    assert ticket is not None
    assert ticket.ticket_id
    assert ticket.title

    marker = f"ai-factory integration test {uuid.uuid4()}"
    board.report_result(ticket, marker)

    query = urllib.parse.urlencode(
        {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}
    )
    url = f"https://api.trello.com/1/cards/{ticket.ticket_id}/actions?filter=commentCard&{query}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
        actions = json.load(response)

    comments = [action["data"]["text"] for action in actions]
    assert marker in comments
