"""Minimal JSON-over-HTTPS helper shared by the infrastructure adapters.

Enforces https at construction time so an adapter can never be pointed at a
`file:` or plain-http URL, and translates transport/status/decoding failures
into ExternalServiceError. Messages name the method and path only: the URL
(which may carry credentials in its query string) is never echoed.
"""

import json
from http.client import HTTPException, HTTPSConnection
from typing import Any
from urllib.parse import urlencode, urlparse

from ai_factory.domain.errors import ExternalServiceError

HTTP_TIMEOUT_SECONDS = 20
ERROR_STATUS_THRESHOLD = 400


class JsonHttpClient:
    """Tiny JSON client bound to one HTTPS service endpoint."""

    def __init__(self, base_url: str, timeout_seconds: int = HTTP_TIMEOUT_SECONDS) -> None:
        """Validate the base URL and store the connection settings.

        Args:
            base_url: HTTPS root of the service, e.g. https://api.trello.com/1.
            timeout_seconds: Timeout applied to every request.

        Raises:
            ValueError: When the base URL is not an absolute https URL.
        """
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"base_url must be an absolute https URL, got {base_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send one request and decode its JSON response.

        Args:
            method: HTTP method to use.
            path: Path appended to the base path, starting with a slash.
            params: Query-string parameters.
            body: JSON-serializable request body, if any.
            headers: Extra request headers.

        Returns:
            The decoded JSON payload, or None for an empty response body.

        Raises:
            ExternalServiceError: On transport, status or decoding failures.
                The message names the method and path only, never the URL.
        """
        query = f"?{urlencode(params)}" if params else ""
        request_headers = dict(headers or {})
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode()
            request_headers.setdefault("Content-Type", "application/json")
        connection = HTTPSConnection(self._host, self._port, timeout=self._timeout_seconds)
        try:
            connection.request(
                method, f"{self._base_path}{path}{query}", body=payload, headers=request_headers
            )
            response = connection.getresponse()
            raw_body = response.read()
        except (OSError, HTTPException) as error:
            raise ExternalServiceError(f"request failed for {method} {path}") from error
        finally:
            connection.close()
        if response.status >= ERROR_STATUS_THRESHOLD:
            raise ExternalServiceError(f"HTTP {response.status} for {method} {path}")
        if not raw_body:
            return None
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise ExternalServiceError(f"invalid JSON response for {method} {path}") from error
