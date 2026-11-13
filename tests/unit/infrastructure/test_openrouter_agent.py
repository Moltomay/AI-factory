"""Behavior tests for the OpenRouter agent adapter, with a scripted stub client (no network)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from ai_factory.domain.agent_policies import (
    CODE_REVIEW_POLICY,
    DEVELOPER_POLICY,
    SPEC_WRITER_POLICY,
)
from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from ai_factory.domain.outcomes import ReviewFeedback
from ai_factory.domain.specification import AcceptanceCriterion, Specification
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

    def _create(self, model: str, messages: list[Any], **kwargs: Any) -> object:
        self.requests.append(
            {"model": model, "messages": list(messages), "tools": kwargs.get("tools")}
        )
        if not self._messages:
            raise AssertionError("stub client ran out of scripted replies")
        outcome = self._messages.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=outcome)])

    def tool_names(self, request_index: int) -> set[str]:
        """Function names offered to the model for one request."""
        tools = self.requests[request_index]["tools"] or []
        return {tool["function"]["name"] for tool in tools}


def _make_agent(tmp_path: Path, client: _StubClient, max_turns: int = 40) -> OpenRouterAgent:
    return OpenRouterAgent("test-key", "test/model", tmp_path, client=client, max_turns=max_turns)


def _make_ticket() -> Ticket:
    return Ticket(ticket_id="42", title="Add hello.txt", description="Create the file.")


def _make_specification() -> Specification:
    return Specification(
        problem="The file does not exist.",
        scope_in=("Create the file.",),
        scope_out=(),
        acceptance_criteria=(
            AcceptanceCriterion(
                id="AC1",
                statement="The file exists with the expected content.",
                ticket_quote="Create the file.",
            ),
        ),
        unknowns=(),
        definition_of_done=("The file is tested.",),
    )


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

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

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

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hi"
    assert len(client.requests) == 2
    tool_messages = [
        message
        for message in client.requests[1]["messages"]
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    assert tool_messages[0]["content"] == "written: hello.txt"
    assert "write_file" in client.tool_names(0)


def test_spec06d_ac9_feedback_is_rendered_for_the_developer(tmp_path: Path) -> None:
    """AC9: severity, category, location, AC and the unverified flag reach the prompt."""
    finding = Finding(
        severity=FindingSeverity.BLOCKER,
        category=FindingCategory.TESTS,
        location="tests/test_parser.py:42",
        message="The assertion holds for any implementation.",
        status=FindingStatus.UNVERIFIED,
        ac="AC3",
    )
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(
        _make_ticket(),
        _make_specification(),
        ReviewFeedback(findings=(finding,), omitted_findings=2),
    )

    user_message = client.requests[0]["messages"][1]["content"]
    assert (
        "- [blocker][tests] tests/test_parser.py:42 — The assertion holds for any "
        "implementation. (AC3) [unverified]"
    ) in user_message
    assert "+2 more findings omitted." in user_message


def test_spec06d_ac9_empty_feedback_has_no_section(tmp_path: Path) -> None:
    """AC9: the first attempt gets no feedback block at all."""
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    user_message = client.requests[0]["messages"][1]["content"]
    assert "previous failed attempt" not in user_message


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

    _make_agent(tmp_path / "workdir", client).implement(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

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
        _make_agent(tmp_path, client, max_turns=2).implement(
            _make_ticket(), _make_specification(), ReviewFeedback()
        )


def test_spec03_ac6_reviews_are_read_only(tmp_path: Path) -> None:
    """AC6: the review stage is not offered the write_file tool."""
    client = _StubClient(
        [_StubMessage(content='{"approved": true, "summary": "ok", "findings": []}')]
    )
    agent = _make_agent(tmp_path, client)

    agent.review(_make_ticket(), _make_specification(), ReviewFeedback())

    assert client.tool_names(0) == READ_ONLY_TOOL_NAMES


def _finding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "severity": "blocker",
        "category": "tests",
        "location": "tests/test_parser.py:42",
        "message": "The assertion holds for any implementation.",
        "evidence": "- assert result is not None",
        "status": "verified",
    }
    payload.update(overrides)
    return payload


def _verdict(*findings: dict[str, object], summary: str = "verdict") -> str:
    return json.dumps({"summary": summary, "findings": list(findings)})


def test_spec06d_ac5_review_verdict_maps_onto_findings(tmp_path: Path) -> None:
    """AC5: every schema field reaches the domain object; unknown keys are ignored."""
    payload = _finding_payload(ac="AC3", unexpected="ignored")
    client = _StubClient([_StubMessage(content=_verdict(payload))])

    outcome = _make_agent(tmp_path, client).review(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

    assert outcome.approved is False
    assert outcome.summary == "verdict"
    finding = outcome.findings[0]
    assert finding.severity is FindingSeverity.BLOCKER
    assert finding.category is FindingCategory.TESTS
    assert finding.status is FindingStatus.VERIFIED
    assert finding.ac == "AC3"


def test_spec06d_ac5_model_approved_field_is_ignored(tmp_path: Path) -> None:
    """AC5: an approving model field cannot override a blocking finding."""
    verdict = json.dumps({"approved": True, "summary": "ok", "findings": [_finding_payload()]})
    client = _StubClient([_StubMessage(content=verdict)])

    outcome = _make_agent(tmp_path, client).review(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

    assert outcome.approved is False


def test_spec06d_ac5_empty_findings_approve(tmp_path: Path) -> None:
    """AC5: an explicit empty finding list is a valid approval."""
    client = _StubClient([_StubMessage(content=_verdict())])

    outcome = _make_agent(tmp_path, client).review(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

    assert outcome.approved is True


INVALID_VERDICTS = [
    "not json",
    '["verdict"]',
    '{"findings": []}',
    '{"summary": "   ", "findings": []}',
    '{"summary": "ok"}',
    '{"summary": "ok", "findings": ["a string"]}',
    _verdict(_finding_payload(severity="critical")),
    _verdict(_finding_payload(category="style")),
    _verdict(_finding_payload(status="maybe")),
    _verdict({"severity": "minor", "category": "tests", "message": "m", "status": "unverified"}),
    _verdict(_finding_payload(evidence="")),
]


@pytest.mark.parametrize("verdict", INVALID_VERDICTS)
def test_spec06d_ac6_invalid_verdict_raises_after_one_retry(tmp_path: Path, verdict: str) -> None:
    """AC6: every malformed verdict is rejected, never guessed."""
    client = _StubClient([_StubMessage(content=verdict), _StubMessage(content=verdict)])

    with pytest.raises(ExternalServiceError, match="after one corrective retry"):
        _make_agent(tmp_path, client).review(
            _make_ticket(), _make_specification(), ReviewFeedback()
        )

    assert len(client.requests) == 2


def test_spec06d_ac6_error_names_the_faulty_field_without_the_reply(tmp_path: Path) -> None:
    """AC6: the failure is debuggable but never echoes the model reply."""
    client = _StubClient(
        [
            _StubMessage(content="secret-token-value"),
            _StubMessage(content="secret-token-value"),
        ]
    )

    with pytest.raises(ExternalServiceError) as raised:
        _make_agent(tmp_path, client).review(
            _make_ticket(), _make_specification(), ReviewFeedback()
        )

    assert "not valid JSON" in str(raised.value)
    assert "secret-token-value" not in str(raised.value)


def test_spec06d_ac7_invalid_verdict_is_corrected_once_without_tools(tmp_path: Path) -> None:
    """AC7: one extra call, without tools, carrying the validation error."""
    client = _StubClient([_StubMessage(content="not json"), _StubMessage(content=_verdict())])

    outcome = _make_agent(tmp_path, client).review(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

    assert outcome.approved is True
    assert len(client.requests) == 2
    assert client.requests[1]["tools"] is None
    correction = client.requests[1]["messages"][-1]["content"]
    assert "not valid JSON" in correction
    assert "severity" in correction


def test_spec06d_ac7_correction_does_not_consume_the_turn_budget(tmp_path: Path) -> None:
    """AC7: the correction sits outside the tool loop, so max_turns=1 still works."""
    client = _StubClient([_StubMessage(content="not json"), _StubMessage(content=_verdict())])

    outcome = _make_agent(tmp_path, client, max_turns=1).review(
        _make_ticket(), _make_specification(), ReviewFeedback()
    )

    assert outcome.approved is True


def test_spec07_ac8_implement_uses_the_developer_policy(tmp_path: Path) -> None:
    """AC8: the developer system prompt is the rendered Coding policy."""
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    assert client.requests[0]["messages"][0]["content"] == DEVELOPER_POLICY.render()


def test_spec07_ac8_review_uses_the_code_review_policy(tmp_path: Path) -> None:
    """AC8: the review system prompt is the rendered Code Review policy."""
    client = _StubClient([_StubMessage(content=_verdict())])

    _make_agent(tmp_path, client).review(_make_ticket(), _make_specification(), ReviewFeedback())

    assert client.requests[0]["messages"][0]["content"] == CODE_REVIEW_POLICY.render()


def test_spec07_ac8_system_prompt_contains_no_target_repository_content(tmp_path: Path) -> None:
    """AC8: the prompt is factory-owned and never embeds the target repository."""
    repository_marker = "target-repository-marker"
    (tmp_path / "AGENTS.md").write_text(repository_marker, encoding="utf-8")
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    system_prompt = client.requests[0]["messages"][0]["content"]
    assert repository_marker not in system_prompt


def test_completion_error_becomes_external_service_error(tmp_path: Path) -> None:
    """An SDK error is surfaced as ExternalServiceError."""
    client = _StubClient([OpenAIError("boom")])

    with pytest.raises(ExternalServiceError):
        _make_agent(tmp_path, client).implement(
            _make_ticket(), _make_specification(), ReviewFeedback()
        )


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


@pytest.mark.parametrize(
    "command_text",
    [
        "git grep --open-files=less foo",
        "git grep -Oless foo",
        "git grep -O less foo",
        "git grep -nOless foo",
        "git log --textc HEAD",
        "git show --ext-d HEAD",
        "git diff --no-i a b",
    ],
)
def test_spec06a_ac4_git_abbreviated_flag_and_pager_short_option_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command_text: str
) -> None:
    """AC4: git's abbreviations and git grep's -O pager cannot bypass the policy."""
    message, runner = _run_one_command(monkeypatch, tmp_path, command_text)

    assert runner.commands == []
    assert "not allowed" in message.lower()


def test_spec06a_ac4_git_path_separator_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4 (non-regression): the -- separator is not mistaken for a refused option."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "git diff -- README.md")

    assert runner.commands == [["/fake/bin/git", "diff", "--", "README.md"]]
    assert "exit code 0" in message


def test_spec06a_ac4_git_diff_order_file_option_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4 (non-regression): -O stays a read-only order file outside git grep."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "git diff -Oorder.txt")

    assert runner.commands == [["/fake/bin/git", "diff", "-Oorder.txt"]]
    assert "exit code 0" in message


def test_spec06a_ac4_git_output_indicator_option_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4 (non-regression): --output-indicator is a distinct read-only flag."""
    message, runner = _run_one_command(monkeypatch, tmp_path, "git diff --output-indicator-new=+")

    assert runner.commands == [["/fake/bin/git", "diff", "--output-indicator-new=+"]]
    assert "exit code 0" in message


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

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

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

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    assert not (tmp_path / path).exists()
    tool_message = _tool_message_after(client, 1)
    assert ".git" in tool_message.lower()


def test_spec06a_ac6_reviews_keep_read_only_tools_and_implement_keeps_write_file(
    tmp_path: Path,
) -> None:
    """AC6: hardening does not change the tool set of the two stages."""
    verdict = '{"approved": true, "summary": "ok", "findings": []}'
    client = _StubClient([_StubMessage(content="done"), _StubMessage(content=verdict)])
    agent = _make_agent(tmp_path, client)

    agent.implement(_make_ticket(), _make_specification(), ReviewFeedback())
    agent.review(_make_ticket(), _make_specification(), ReviewFeedback())

    assert "write_file" in client.tool_names(0)
    assert client.tool_names(1) == READ_ONLY_TOOL_NAMES


def _spec_payload() -> dict[str, object]:
    return {
        "status": "ready",
        "problem": "The file does not exist.",
        "scope_in": ["Create the file."],
        "scope_out": [],
        "acceptance_criteria": [
            {
                "id": "AC1",
                "statement": "The file exists with the expected content.",
                "ticket_quote": "Create the file.",
            }
        ],
        "unknowns": [],
        "definition_of_done": ["The file is tested."],
    }


def test_spec06e_ac11_specify_uses_the_spec_policy_without_tools(tmp_path: Path) -> None:
    """AC11: the Spec stage renders its policy and is offered no tool at all."""
    client = _StubClient([_StubMessage(content=json.dumps(_spec_payload()))])

    outcome = _make_agent(tmp_path, client).specify(_make_ticket())

    assert outcome.specification is not None
    assert client.requests[0]["messages"][0]["content"] == SPEC_WRITER_POLICY.render()
    assert client.requests[0]["tools"] is None
    assert "Create the file." in client.requests[0]["messages"][1]["content"]


def test_spec06e_ac11_specify_parses_a_clarification(tmp_path: Path) -> None:
    """AC11: a clarification reply becomes an outcome carrying its questions."""
    payload = {"status": "needs_clarification", "questions": ["Which format?"]}
    client = _StubClient([_StubMessage(content=json.dumps(payload))])

    outcome = _make_agent(tmp_path, client).specify(_make_ticket())

    assert outcome.specification is None
    assert outcome.questions == ("Which format?",)


def test_spec06e_ac11_invalid_specification_is_corrected_once_without_tools(
    tmp_path: Path,
) -> None:
    """AC11: one corrective retry carries the validation error, without tools."""
    client = _StubClient(
        [_StubMessage(content="not json"), _StubMessage(content=json.dumps(_spec_payload()))]
    )

    outcome = _make_agent(tmp_path, client).specify(_make_ticket())

    assert outcome.specification is not None
    assert len(client.requests) == 2
    assert client.requests[1]["tools"] is None
    correction = client.requests[1]["messages"][-1]["content"]
    assert "not valid JSON" in correction
    assert '"acceptance_criteria"' in correction


def test_spec06e_ac11_invalid_specification_twice_fails_loudly(tmp_path: Path) -> None:
    """AC11: a second malformed reply stops the run with ExternalServiceError."""
    invalid = json.dumps({**_spec_payload(), "acceptance_criteria": []})
    client = _StubClient([_StubMessage(content=invalid), _StubMessage(content=invalid)])

    with pytest.raises(ExternalServiceError, match="after one corrective retry"):
        _make_agent(tmp_path, client).specify(_make_ticket())

    assert len(client.requests) == 2


def test_spec06e_ac11_specify_refuses_a_tool_call_when_none_is_offered(
    tmp_path: Path,
) -> None:
    """AC11: a tool call is a protocol violation when the Spec stage offers no tool."""
    client = _StubClient(
        [_StubMessage(tool_calls=[_StubToolCall("read_file", {"path": "hello.txt"})])]
    )

    with pytest.raises(ExternalServiceError, match="none was offered"):
        _make_agent(tmp_path, client).specify(_make_ticket())

    assert len(client.requests) == 1


def test_spec06e_ac11_error_names_the_faulty_field_without_the_reply(
    tmp_path: Path,
) -> None:
    """AC11: the failure is debuggable but never echoes the model reply."""
    client = _StubClient(
        [_StubMessage(content="secret-token-value"), _StubMessage(content="secret-token-value")]
    )

    with pytest.raises(ExternalServiceError) as raised:
        _make_agent(tmp_path, client).specify(_make_ticket())

    assert "not valid JSON" in str(raised.value)
    assert "secret-token-value" not in str(raised.value)


def test_spec06e_ac11_implement_renders_the_specification(tmp_path: Path) -> None:
    """AC11: the Coding agent receives the validated specification in its prompt."""
    client = _StubClient([_StubMessage(content="done")])

    _make_agent(tmp_path, client).implement(_make_ticket(), _make_specification(), ReviewFeedback())

    user_message = client.requests[0]["messages"][1]["content"]
    assert "Validated specification:" in user_message
    assert "AC1: The file exists with the expected content." in user_message


def test_spec06e_ac11_review_renders_the_specification(tmp_path: Path) -> None:
    """AC11: the Code Review agent receives the same validated specification."""
    client = _StubClient([_StubMessage(content=_verdict())])

    _make_agent(tmp_path, client).review(_make_ticket(), _make_specification(), ReviewFeedback())

    user_message = client.requests[0]["messages"][1]["content"]
    assert "Validated specification:" in user_message
    assert "AC1: The file exists with the expected content." in user_message
