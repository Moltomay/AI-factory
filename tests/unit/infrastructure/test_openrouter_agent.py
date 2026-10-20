"""Behavior tests for the OpenRouter agent adapter, with a scripted stub client (no network)."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure.openrouter_agent import OpenRouterAgent

READ_ONLY_TOOL_NAMES = {"read_file", "list_files", "run_command"}


class _StubToolCall:
    def __init__(
        self, tool_name: str, arguments: dict[str, object], call_id: str = "call-1"
    ) -> None:
        self.id = call_id
        self.function = SimpleNamespace(name=tool_name, arguments=json.dumps(arguments))


class _StubMessage:
    def __init__(
        self, content: str | None = None, tool_calls: list[_StubToolCall] | None = None
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _StubClient:
    """Replays scripted assistant messages and records completion requests."""

    def __init__(self, messages: list[object]) -> None:
        self._messages = list(messages)
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model: str, messages: list[Any], tools: list[dict[str, Any]]) -> object:
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        outcome = self._messages.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=outcome)])

    def tool_names(self, request_index: int) -> set[str]:
        """Function names offered to the model for one request."""
        tools = self.requests[request_index]["tools"]
        return {tool["function"]["name"] for tool in tools}


def _make_agent(tmp_path: Path, client: _StubClient, max_turns: int = 40) -> OpenRouterAgent:
    return OpenRouterAgent("test-key", "test/model", tmp_path, client=client, max_turns=max_turns)


def _make_ticket() -> Ticket:
    return Ticket(ticket_id="42", title="Add hello.txt", description="Create the file.")


def test_ac5_implement_writes_file_through_tool_loop(tmp_path: Path) -> None:
    """AC5: a write_file tool call is executed in the workdir and fed back to the model."""
    client = _StubClient(
        [
            _StubMessage(
                tool_calls=[_StubToolCall("write_file", {"path": "hello.txt", "content": "hi"})]
            ),
            _StubMessage(content="done"),
        ]
    )

    _make_agent(tmp_path, client).implement(_make_ticket(), ())

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hi"
    assert len(client.requests) == 2
    tool_messages = [
        message
        for message in client.requests[1]["messages"]
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    assert tool_messages[0]["content"] == "written: hello.txt"
    assert "write_file" in client.tool_names(0)


def test_ac5_implement_reports_feedback_in_prompt(tmp_path: Path) -> None:
    """AC5: feedback from a failed attempt is part of the user message."""
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), ("Missing test",))

    user_message = client.requests[0]["messages"][1]["content"]
    assert "Missing test" in user_message


def test_ac5_path_outside_workdir_is_refused(tmp_path: Path) -> None:
    """AC5: a tool call escaping the workdir is refused and reported to the model."""
    client = _StubClient(
        [
            _StubMessage(
                tool_calls=[_StubToolCall("write_file", {"path": "../escape.txt", "content": "x"})]
            ),
            _StubMessage(content="done"),
        ]
    )

    _make_agent(tmp_path / "workdir", client).implement(_make_ticket(), ())

    assert not (tmp_path / "escape.txt").exists()
    tool_message = next(
        message
        for message in client.requests[1]["messages"]
        if isinstance(message, dict) and message.get("role") == "tool"
    )
    assert "escapes the repository" in tool_message["content"]


def test_ac6_agent_stops_at_turn_budget(tmp_path: Path) -> None:
    """AC6: a model that never stops calling tools fails loudly at the budget."""
    client = _StubClient(
        [
            _StubMessage(tool_calls=[_StubToolCall("list_files", {})]),
            _StubMessage(tool_calls=[_StubToolCall("list_files", {})]),
        ]
    )

    with pytest.raises(ExternalServiceError, match="turns budget"):
        _make_agent(tmp_path, client, max_turns=2).implement(_make_ticket(), ())


def test_ac6_reviews_are_read_only(tmp_path: Path) -> None:
    """AC6: review stages are not offered the write_file tool."""
    client = _StubClient(
        [
            _StubMessage(content='{"approved": true, "summary": "ok", "findings": []}'),
            _StubMessage(content='{"approved": true, "summary": "ok", "findings": []}'),
        ]
    )
    agent = _make_agent(tmp_path, client)

    agent.quality_review(_make_ticket(), ())
    agent.final_review(_make_ticket(), ())

    assert client.tool_names(0) == READ_ONLY_TOOL_NAMES
    assert client.tool_names(1) == READ_ONLY_TOOL_NAMES


def test_ac7_review_verdict_is_parsed(tmp_path: Path) -> None:
    """AC7: a JSON verdict becomes a StageOutcome with its findings."""
    client = _StubClient(
        [
            _StubMessage(
                content=(
                    '{"approved": false, "summary": "tests missing", '
                    '"findings": ["add a unit test"]}'
                )
            )
        ]
    )

    outcome = _make_agent(tmp_path, client).quality_review(_make_ticket(), ())

    assert outcome.approved is False
    assert outcome.summary == "tests missing"
    assert outcome.findings == ("add a unit test",)


@pytest.mark.parametrize(
    "verdict",
    [
        "not json",
        '["approved"]',
        '{"approved": "yes", "summary": "ok", "findings": []}',
        '{"approved": true, "findings": []}',
        '{"approved": true, "summary": "ok", "findings": [1]}',
    ],
)
def test_ac7_invalid_review_verdict_fails_loudly(tmp_path: Path, verdict: str) -> None:
    """AC7: a malformed verdict raises instead of being guessed."""
    client = _StubClient([_StubMessage(content=verdict)])

    with pytest.raises(ExternalServiceError):
        _make_agent(tmp_path, client).final_review(_make_ticket(), ())


def test_ac4_completion_error_becomes_external_service_error(tmp_path: Path) -> None:
    """AC4: an SDK error is surfaced as ExternalServiceError."""
    client = _StubClient([OpenAIError("boom")])

    with pytest.raises(ExternalServiceError):
        _make_agent(tmp_path, client).implement(_make_ticket(), ())
