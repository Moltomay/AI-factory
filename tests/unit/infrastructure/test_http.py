"""Behavior tests for the JSON-over-HTTPS client, with a fake connection (no network)."""

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import http as http_module
from ai_factory.infrastructure.http import JsonHttpClient

BASE_URL = "https://api.example.test/1"


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeConnection:
    def __init__(
        self, response: _FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.requests.append((method, url, body, dict(headers or {})))
        if self.error is not None:
            raise self.error

    def getresponse(self) -> _FakeResponse:
        assert self.response is not None
        return self.response

    def close(self) -> None:
        self.closed = True


def _install_connection(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse | None = None,
    error: Exception | None = None,
) -> _FakeConnection:
    connection = _FakeConnection(response=response, error=error)

    def fake_connection(host: str, port: int | None, timeout: int) -> _FakeConnection:
        return connection

    monkeypatch.setattr(http_module, "HTTPSConnection", fake_connection)
    return connection


def test_get_returns_decoded_json_and_builds_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GET returns the decoded payload with the query string applied."""
    connection = _install_connection(monkeypatch, _FakeResponse(200, b'{"id": "card-1"}'))

    payload = JsonHttpClient(BASE_URL).request_json(
        "GET", "/lists/list-1/cards", {"fields": "id,name"}
    )

    assert payload == {"id": "card-1"}
    method, url, body, _ = connection.requests[0]
    assert (method, url, body) == ("GET", "/1/lists/list-1/cards?fields=id%2Cname", None)
    assert connection.closed


def test_post_sends_json_body_with_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST serializes the body as JSON and closes the connection."""
    connection = _install_connection(monkeypatch, _FakeResponse(200, b"{}"))

    JsonHttpClient(BASE_URL).request_json("POST", "/cards/c1/actions/comments", body={"text": "hi"})

    method, url, body, headers = connection.requests[0]
    assert method == "POST"
    assert url == "/1/cards/c1/actions/comments"
    assert body == b'{"text": "hi"}'
    assert headers["Content-Type"] == "application/json"
    assert connection.closed


def test_empty_body_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty response body decodes to None."""
    _install_connection(monkeypatch, _FakeResponse(204, b""))

    assert JsonHttpClient(BASE_URL).request_json("DELETE", "/things/1") is None


def test_error_status_raises_without_leaking_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An HTTP error raises ExternalServiceError, never echoing the query string."""
    _install_connection(monkeypatch, _FakeResponse(401, b""))

    with pytest.raises(ExternalServiceError) as exc_info:
        JsonHttpClient(BASE_URL).request_json("GET", "/members/me", {"token": "super-secret-value"})

    message = str(exc_info.value)
    assert "HTTP 401" in message
    assert "super-secret-value" not in message


def test_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An undecodable body raises ExternalServiceError."""
    _install_connection(monkeypatch, _FakeResponse(200, b"not json"))

    with pytest.raises(ExternalServiceError):
        JsonHttpClient(BASE_URL).request_json("GET", "/lists/list-1/cards")


def test_transport_error_raises_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure raises ExternalServiceError and closes the connection."""
    connection = _install_connection(monkeypatch, error=OSError("network down"))

    with pytest.raises(ExternalServiceError):
        JsonHttpClient(BASE_URL).request_json("GET", "/lists/list-1/cards")

    assert connection.closed


def test_non_https_base_url_is_rejected() -> None:
    """A non-https base URL is refused at construction time."""
    with pytest.raises(ValueError, match="absolute https URL"):
        JsonHttpClient("http://api.example.test/1")
