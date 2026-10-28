"""Behavior tests for the OpenRouter agent adapter, with a scripted stub client (no network)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure import openrouter_agent as agent_module
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


class _FakeCommandRunner:
    """Records agent commands and returns a scripted result."""

    def __init__(self, returncode: int = 0, stdout: str = "ok", stderr: str = "") -> None:
        self.commands: list[list[str]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def __call__(
        self, command: list[str], cwd: Path, timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, self._returncode, self._stdout, self._stderr)


def _run_one_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command_text: str,
    runner: _FakeCommandRunner | None = None,
) -> tuple[str, _FakeCommandRunner]:
    """Run one run_command tool call and return the tool message and fake runner."""
    fake_runner = runner or _FakeCommandRunner()
    monkeypatch.setattr(agent_module, "run_process", fake_runner)
    monkeypatch.setattr(agent_module.shutil, "which", lambda name: f"/fake/bin/{name}")
    client = _StubClient(
        [
            _StubMessage(tool_calls=[_StubToolCall("run_command", {"command": command_text})]),
            _StubMessage(content="done"),
        ]
    )

    _make_agent(tmp_path, client).implement(_make_ticket(), ())

    tool_message = next(
        message["content"]
        for message in client.requests[1]["messages"]
        if isinstance(message, dict) and message.get("role") == "tool"
    )
    return tool_message, fake_runner


def _tool_message_after(client: _StubClient, request_index: int) -> str:
    """Return the content of the first tool message for one completion request."""
    return next(
        message["content"]
        for message in client.requests[request_index]["messages"]
        if isinstance(message, dict) and message.get("role") == "tool"
    )


def test_spec03_ac5_implement_writes_file_through_tool_loop(tmp_path: Path) -> None:
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


def test_spec03_ac5_implement_reports_feedback_in_prompt(tmp_path: Path) -> None:
    """AC5: feedback from a failed attempt is part of the user message."""
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), ("Missing test",))

    user_message = client.requests[0]["messages"][1]["content"]
    assert "Missing test" in user_message


def test_spec03_ac5_path_outside_workdir_is_refused(tmp_path: Path) -> None:
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


def test_spec03_ac6_agent_stops_at_turn_budget(tmp_path: Path) -> None:
    """AC6: a model that never stops calling tools fails loudly at the budget."""
    client = _StubClient(
        [
            _StubMessage(tool_calls=[_StubToolCall("list_files", {})]),
            _StubMessage(tool_calls=[_StubToolCall("list_files", {})]),
        ]
    )

    with pytest.raises(ExternalServiceError, match="turns budget"):
        _make_agent(tmp_path, client, max_turns=2).implement(_make_ticket(), ())


def test_spec03_ac6_reviews_are_read_only(tmp_path: Path) -> None:
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


def test_spec03_ac7_review_verdict_is_parsed(tmp_path: Path) -> None:
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
def test_spec03_ac7_invalid_review_verdict_fails_loudly(tmp_path: Path, verdict: str) -> None:
    """AC7: a malformed verdict raises instead of being guessed."""
    client = _StubClient([_StubMessage(content=verdict)])

    with pytest.raises(ExternalServiceError):
        _make_agent(tmp_path, client).final_review(_make_ticket(), ())


def test_completion_error_becomes_external_service_error(tmp_path: Path) -> None:
    """An SDK error is surfaced as ExternalServiceError."""
    client = _StubClient([OpenAIError("boom")])

    with pytest.raises(ExternalServiceError):
        _make_agent(tmp_path, client).implement(_make_ticket(), ())


def test_spec06a_ac3_approved_executable_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: an allowlisted executable is resolved and executed."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "ruff check .")

    assert runner.commands == [["/fake/bin/ruff", "check", "."]]
    assert "exit code 0" in message


def test_spec06a_ac3_disallowed_executable_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: a non-allowlisted executable is refused without crashing the run."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "curl https://example.com")

    assert runner.commands == []
    assert "not allowed" in message.lower()


def test_spec06a_ac3_executable_path_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: only a bare executable name is accepted."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "./git status")

    assert runner.commands == []
    assert "path" in message.lower()


def test_spec06a_ac4_read_only_git_subcommand_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4: an inspection subcommand is executed."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "git status --short")

    assert runner.commands == [["/fake/bin/git", "status", "--short"]]
    assert "exit code 0" in message


@pytest.mark.parametrize(
    "command_text",
    [
        "git push origin main",
        "git commit -m change",
        "git add -A",
        "git switch main",
        "git checkout main",
        "git reset --hard",
        "git clean -fd",
        "git clone https://example.com/repo.git",
    ],
)
def test_spec06a_ac4_writing_git_subcommand_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command_text: str
) -> None:
    """AC4: a git command that changes the repository is refused."""
    message, runner = _run_one_command(monkeypatch, tmp_path, command_text)

    assert runner.commands == []
    assert "read-only" in message.lower()


@pytest.mark.parametrize(
    "command_text",
    ["git fetch origin", "git pull", "git ls-remote origin"],
)
def test_spec06a_ac4_network_git_subcommand_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command_text: str
) -> None:
    """AC4: a git command that uses the network is refused."""
    message, runner = _run_one_command(monkeypatch, tmp_path, command_text)

    assert runner.commands == []
    assert "read-only" in message.lower()


@pytest.mark.parametrize(
    "command_text",
    [
        "git -C /tmp status",
        "git -c core.fsmonitor=evil status",
        "git --config-env=core.fsmonitor=EVIL status",
        "git --git-dir=/tmp/.git status",
        "git --work-tree=/tmp status",
        "git --exec-path=/tmp status",
        "git -p log",
        "git --paginate log",
        "git --version",
        "git",
    ],
)
def test_spec06a_ac4_git_global_option_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command_text: str
) -> None:
    """AC4: a git global option or a missing subcommand is refused."""
    message, runner = _run_one_command(monkeypatch, tmp_path, command_text)

    assert runner.commands == []
    assert "read-only" in message.lower()


@pytest.mark.parametrize(
    "command_text",
    [
        "git diff --output=out.txt",
        "git log --outp=out.txt",
        "git diff --no-index a b",
        "git show --textconv HEAD",
        "git log --ext-diff",
        "git grep --open-files-in-pager=less foo",
    ],
)
def test_spec06a_ac4_git_write_flag_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command_text: str
) -> None:
    """AC4: a git flag that writes a file or runs a program is refused."""
    message, runner = _run_one_command(monkeypatch, tmp_path, command_text)

    assert runner.commands == []
    assert "not allowed" in message.lower()


@pytest.mark.parametrize("path", [".git/config", ".GIT/config"])
def test_spec06a_ac5_read_file_refuses_dot_git_path(tmp_path: Path, path: str) -> None:
    """AC5: the file tools cannot read the git metadata."""
    secret_path = tmp_path / path
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("token-value", encoding="utf-8")
    client = _StubClient(
        [
            _StubMessage(tool_calls=[_StubToolCall("read_file", {"path": path})]),
            _StubMessage(content="done"),
        ]
    )

    _make_agent(tmp_path, client).implement(_make_ticket(), ())

    tool_message = _tool_message_after(client, 1)
    assert "token-value" not in tool_message
    assert ".git" in tool_message.lower()


@pytest.mark.parametrize("path", [".git/config", ".GIT/config"])
def test_spec06a_ac5_write_file_refuses_dot_git_path(tmp_path: Path, path: str) -> None:
    """AC5: the file tools cannot write the git metadata."""
    client = _StubClient(
        [
            _StubMessage(tool_calls=[_StubToolCall("write_file", {"path": path, "content": "x"})]),
            _StubMessage(content="done"),
        ]
    )

    _make_agent(tmp_path, client).implement(_make_ticket(), ())

    assert not (tmp_path / path).exists()
    tool_message = _tool_message_after(client, 1)
    assert ".git" in tool_message.lower()


def test_spec06a_ac6_reviews_keep_read_only_tools_and_implement_keeps_write_file(
    tmp_path: Path,
) -> None:
    """AC6: hardening does not change the tool set of the three stages."""
    verdict = '{"approved": true, "summary": "ok", "findings": []}'
    client = _StubClient(
        [
            _StubMessage(content="done"),
            _StubMessage(content=verdict),
            _StubMessage(content=verdict),
        ]
    )
    agent = _make_agent(tmp_path, client)

    agent.implement(_make_ticket(), ())
    agent.quality_review(_make_ticket(), ())
    agent.final_review(_make_ticket(), ())

    assert "write_file" in client.tool_names(0)
    assert client.tool_names(1) == READ_ONLY_TOOL_NAMES
    assert client.tool_names(2) == READ_ONLY_TOOL_NAMES
