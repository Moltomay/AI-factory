"""OpenRouter code agent: LLM implementation of the CodeAgent port with a tool loop.

The model works inside the repository clone through a small, explicit tool set;
reviews are read-only and must return a JSON verdict. Every completion or tool
protocol failure is surfaced as ExternalServiceError so the pipeline stops loudly.
"""

import json
import shlex
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI, OpenAIError

from ai_factory.domain.agent_policies import VERDICT_SCHEMA, policy_for
from ai_factory.domain.errors import ExternalServiceError, InvalidFindingError
from ai_factory.domain.findings import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from ai_factory.domain.outcomes import ReviewFeedback, StageOutcome
from ai_factory.domain.pipeline import AgentRole
from ai_factory.domain.ticket import Ticket
from ai_factory.infrastructure.process import run_process

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_AGENT_TURNS = 40
COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_OUTPUT_CHARS = 4000
MAX_FILE_CHARS = 40000
MAX_LISTED_ENTRIES = 200
ALLOWED_EXECUTABLES = frozenset({"git", "python", "python3", "pytest", "ruff"})
GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "show", "rev-parse", "ls-files", "grep"}
)
# Git accepts any unambiguous abbreviation of a long option, and git grep runs
# the -O / --open-files-in-pager value through a shell: match the refused flags
# by prefix, not by exact name.
GIT_REFUSED_FLAGS = (
    "--no-index",
    "--textconv",
    "--ext-diff",
    "--open-files-in-pager",
    "--output",
)
GIT_PAGER_SUBCOMMAND = "grep"
GIT_PAGER_SHORT_OPTION = "O"
GIT_PATH_SEPARATOR = "--"
GIT_DIRECTORY_NAME = ".git"
WINDOWS_EXECUTABLE_SUFFIX = ".exe"

CORRECTION_INSTRUCTION_TEMPLATE = (
    "Your previous reply was rejected: {reason}. "
    "Reply with one JSON object and nothing else, matching this schema: "
)
FEEDBACK_SECTION_HEADER = "Findings from the previous failed attempt:"
FEEDBACK_LINE_TEMPLATE = "- [{severity}][{category}] {location} — {message}"
FEEDBACK_AC_TEMPLATE = " ({ac})"
FEEDBACK_UNVERIFIED_SUFFIX = " [unverified]"
FEEDBACK_OMITTED_TEMPLATE = "+{count} more findings omitted."


class _ToolCallError(Exception):
    """Invalid tool call from the model; its message is fed back to the model."""


class _VerdictError(ValueError):
    """Raised when a review verdict cannot be parsed; triggers one correction."""


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_value(enum_type: type[EnumT], raw: object, field_name: str) -> EnumT:
    """Map a JSON string onto a closed enum, naming the field when it is wrong."""
    if not isinstance(raw, str):
        raise _VerdictError(f"{field_name} must be a string")
    try:
        return enum_type(raw)
    except ValueError as error:
        allowed = ", ".join(member.value for member in enum_type)
        raise _VerdictError(f"{field_name} must be one of: {allowed}") from error


def _text(payload: dict[str, object], name: str, prefix: str) -> str:
    """Read a required string field of a finding."""
    value = payload.get(name)
    if not isinstance(value, str):
        raise _VerdictError(f"{prefix}.{name} must be a string")
    return value


def _render_finding(finding: Finding) -> str:
    """Render one finding as a single feedback line for the developer."""
    line = FEEDBACK_LINE_TEMPLATE.format(
        severity=finding.severity.value,
        category=finding.category.value,
        location=finding.location,
        message=finding.message,
    )
    if finding.ac:
        line += FEEDBACK_AC_TEMPLATE.format(ac=finding.ac)
    if finding.status is FindingStatus.UNVERIFIED:
        line += FEEDBACK_UNVERIFIED_SUFFIX
    return line


def _render_feedback(feedback: ReviewFeedback) -> str:
    """Render the feedback block, or an empty string when there is nothing to fix."""
    if not feedback.findings:
        return ""
    lines = [FEEDBACK_SECTION_HEADER]
    lines.extend(_render_finding(finding) for finding in feedback.findings)
    if feedback.omitted_findings:
        lines.append(FEEDBACK_OMITTED_TEMPLATE.format(count=feedback.omitted_findings))
    return "\n".join(lines)


def _executable_name(raw_name: str) -> str:
    """Return the bare, lowercase executable name.

    Args:
        raw_name: First token of the command sent by the model.

    Returns:
        The executable name without a path or a Windows suffix.

    Raises:
        _ToolCallError: When the token contains a path separator.
    """
    if "/" in raw_name or "\\" in raw_name:
        raise _ToolCallError(f"executable path is not allowed: {raw_name}")
    name = raw_name.lower()
    if name.endswith(WINDOWS_EXECUTABLE_SUFFIX):
        return name[: -len(WINDOWS_EXECUTABLE_SUFFIX)]
    return name


def _resolve_allowed_executable(name: str) -> str:
    """Resolve an approved executable on PATH.

    Args:
        name: Bare, lowercase executable name.

    Returns:
        Absolute path of the executable.

    Raises:
        _ToolCallError: When the executable is not approved or not found.
    """
    if name not in ALLOWED_EXECUTABLES:
        raise _ToolCallError(f"executable is not allowed: {name}")
    executable = shutil.which(name)
    if executable is None:
        raise _ToolCallError(f"executable not found: {name}")
    return executable


def _is_refused_long_option(argument: str) -> bool:
    """Tell whether a long option is, or abbreviates, a refused git flag.

    Git accepts any unambiguous prefix of a long option, so comparing exact
    names would let --open-files or --textc slip through the policy.

    Args:
        argument: One token after the git subcommand.

    Returns:
        True when the option name is a prefix of a refused flag. The bare --
        separator is never treated as an option.
    """
    if not argument.startswith("--"):
        return False
    option_name = argument.split("=", 1)[0]
    if option_name == GIT_PATH_SEPARATOR:
        return False
    return any(refused.startswith(option_name) for refused in GIT_REFUSED_FLAGS)


def _contains_short_option(argument: str, option: str) -> bool:
    """Tell whether a short-option token or cluster contains one option letter.

    Args:
        argument: One token after the git subcommand.
        option: Short option letter to look for.

    Returns:
        True for tokens such as -O, -Oless or -nOless.
    """
    if not argument.startswith("-") or argument.startswith("--"):
        return False
    return option in argument[1:]


def _check_read_only_git(arguments: list[str]) -> None:
    """Refuse a git invocation that is not a read-only inspection.

    Args:
        arguments: Tokens after the git executable.

    Raises:
        _ToolCallError: When the subcommand, a global option or a file-writing
            flag is not allowed.
    """
    if not arguments:
        raise _ToolCallError("git requires a read-only subcommand")
    subcommand = arguments[0]
    if subcommand.startswith("-") or subcommand not in GIT_READ_ONLY_SUBCOMMANDS:
        raise _ToolCallError(f"git subcommand is not allowed (read-only): {subcommand}")
    for argument in arguments[1:]:
        if _is_refused_long_option(argument):
            raise _ToolCallError(f"git option is not allowed: {argument}")
        if subcommand == GIT_PAGER_SUBCOMMAND and _contains_short_option(
            argument, GIT_PAGER_SHORT_OPTION
        ):
            raise _ToolCallError(f"git option is not allowed: {argument}")


def _function_tool(
    name: str,
    description: str,
    properties: dict[str, str | dict[str, str]],
    required: list[str],
) -> dict[str, Any]:
    """Build one OpenAI function-tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_READ_FILE_TOOL = _function_tool(
    "read_file",
    "Read a UTF-8 text file relative to the repository root.",
    {"path": {"type": "string"}},
    ["path"],
)
_LIST_FILES_TOOL = _function_tool(
    "list_files",
    "List repository files as relative paths, excluding .git.",
    {"path": {"type": "string", "description": "Directory to list; default is the root."}},
    [],
)
_WRITE_FILE_TOOL = _function_tool(
    "write_file",
    "Create or overwrite a UTF-8 text file relative to the repository root.",
    {"path": {"type": "string"}, "content": {"type": "string"}},
    ["path", "content"],
)
_RUN_COMMAND_TOOL = _function_tool(
    "run_command",
    "Run one command (no shell operators) in the repository root.",
    {"command": {"type": "string"}},
    ["command"],
)

_READ_ONLY_TOOLS = [_READ_FILE_TOOL, _LIST_FILES_TOOL, _RUN_COMMAND_TOOL]
_IMPLEMENT_TOOLS = [*_READ_ONLY_TOOLS, _WRITE_FILE_TOOL]


class OpenRouterAgent:
    """CodeAgent backed by an OpenRouter chat model (tool loop confined to a workdir)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        workdir: Path,
        client: OpenAI | None = None,
        max_turns: int = MAX_AGENT_TURNS,
    ) -> None:
        """Store the model configuration.

        Args:
            api_key: OpenRouter API key (empty is allowed when a client is injected).
            model: OpenRouter model identifier.
            workdir: Repository clone the tools may read and write.
            client: Pre-built OpenAI-compatible client; one is created when omitted.
            max_turns: Maximum LLM turns before the loop fails loudly.
        """
        self._model = model
        self._workdir = Path(workdir).resolve()
        self._client = client or OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
        self._max_turns = max_turns

    def implement(self, ticket: Ticket, feedback: ReviewFeedback) -> None:
        """Implement the ticket inside the workdir (writes allowed)."""
        self._run_agent(
            policy_for(AgentRole.DEVELOPER).render(), _IMPLEMENT_TOOLS, ticket, feedback
        )

    def review(self, ticket: Ticket, feedback: ReviewFeedback) -> StageOutcome:
        """Review the current repository state read-only and return the verdict."""
        return self._review(
            policy_for(AgentRole.CODE_REVIEWER).render(), _READ_ONLY_TOOLS, ticket, feedback
        )

    def _review(
        self,
        system_prompt: str,
        tools: list[dict[str, Any]],
        ticket: Ticket,
        feedback: ReviewFeedback,
    ) -> StageOutcome:
        """Run a review stage and parse its verdict, correcting it once if needed."""
        content = self._run_agent(system_prompt, tools, ticket, feedback)
        try:
            return self._parse_verdict(content)
        except _VerdictError as error:
            return self._correct_verdict(system_prompt, ticket, feedback, content, error)

    def _correct_verdict(
        self,
        system_prompt: str,
        ticket: Ticket,
        feedback: ReviewFeedback,
        rejected_content: str,
        error: _VerdictError,
    ) -> StageOutcome:
        """Ask the model once to reformat its verdict, without tools.

        The tool transcript is not replayed: this is a formatting correction,
        not a second review, and it must not consume the agent turn budget.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._user_message(ticket, feedback)},
            {"role": "assistant", "content": rejected_content},
            {
                "role": "user",
                "content": CORRECTION_INSTRUCTION_TEMPLATE.format(reason=error) + VERDICT_SCHEMA,
            },
        ]
        corrected = self._next_message(messages)
        try:
            return self._parse_verdict(corrected.content or "")
        except _VerdictError as second_error:
            raise ExternalServiceError(
                f"review verdict is invalid after one corrective retry: {second_error}"
            ) from second_error

    def _run_agent(
        self,
        system_prompt: str,
        tools: list[dict[str, Any]],
        ticket: Ticket,
        feedback: ReviewFeedback,
    ) -> str:
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._user_message(ticket, feedback)},
        ]
        for _turn in range(self._max_turns):
            message = self._next_message(messages, tools)
            messages.append(message)
            if not message.tool_calls:
                return message.content or ""
            for tool_call in message.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self._execute_tool(tool_call),
                    }
                )
        raise ExternalServiceError(f"agent exceeded the {self._max_turns} turns budget")

    def _next_message(self, messages: list[Any], tools: list[dict[str, Any]] | None = None) -> Any:
        request: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools is not None:
            request["tools"] = tools
        try:
            completion = self._client.chat.completions.create(**request)
        except OpenAIError as error:
            raise ExternalServiceError(f"OpenRouter completion failed: {error}") from error
        return completion.choices[0].message

    def _execute_tool(self, tool_call: Any) -> str:
        handlers = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_files": self._list_files,
            "run_command": self._run_command,
        }
        handler = handlers.get(tool_call.function.name)
        if handler is None:
            return f"Error: unknown tool {tool_call.function.name!r}."
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            return "Error: tool arguments are not valid JSON."
        if not isinstance(arguments, dict):
            return "Error: tool arguments must be a JSON object."
        try:
            return handler(arguments)
        except _ToolCallError as error:
            return f"Error: {error}"

    def _read_file(self, arguments: dict[str, Any]) -> str:
        path = self._resolve(arguments.get("path"))
        if not path.is_file():
            raise _ToolCallError(f"file not found: {arguments.get('path')}")
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]

    def _write_file(self, arguments: dict[str, Any]) -> str:
        path = self._resolve(arguments.get("path"))
        if "content" not in arguments:
            raise _ToolCallError("write_file requires a content argument")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(arguments["content"]), encoding="utf-8")
        return f"written: {path.relative_to(self._workdir).as_posix()}"

    def _list_files(self, arguments: dict[str, Any]) -> str:
        base = self._resolve(arguments.get("path", "."))
        if not base.is_dir():
            raise _ToolCallError(f"not a directory: {arguments.get('path')}")
        entries: list[str] = []
        for candidate in sorted(base.rglob("*")):
            relative = candidate.relative_to(self._workdir)
            if ".git" in relative.parts:
                continue
            entries.append(relative.as_posix())
            if len(entries) >= MAX_LISTED_ENTRIES:
                break
        return "\n".join(entries) if entries else "(empty)"

    def _run_command(self, arguments: dict[str, Any]) -> str:
        """Run one allowlisted command inside the workdir and return its output.

        Args:
            arguments: Tool arguments; ``command`` holds the shell-like text.

        Returns:
            Exit code, stdout and stderr, truncated to the output limit.

        Raises:
            _ToolCallError: When the command is empty, not allowlisted, or a
                git invocation that is not read-only.
        """
        command_text = str(arguments.get("command", "")).strip()
        if not command_text:
            raise _ToolCallError("run_command requires a command argument")
        parts = shlex.split(command_text, posix=True)
        if not parts:
            raise _ToolCallError("run_command requires a command argument")
        name = _executable_name(parts[0])
        executable = _resolve_allowed_executable(name)
        if name == "git":
            _check_read_only_git(parts[1:])
        try:
            result = run_process([executable, *parts[1:]], self._workdir, COMMAND_TIMEOUT_SECONDS)
        except ExternalServiceError as error:
            raise _ToolCallError(str(error)) from error
        output = (
            f"exit code {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return output[:MAX_COMMAND_OUTPUT_CHARS]

    def _resolve(self, raw_path: str | None) -> Path:
        """Resolve a tool path inside the workdir and refuse escapes and .git.

        Args:
            raw_path: Path sent by the model, relative to the workdir.

        Returns:
            Absolute path inside the workdir.

        Raises:
            _ToolCallError: When the path is missing, escapes the workdir, or
                targets the git metadata directory.
        """
        if not raw_path:
            raise _ToolCallError("path argument is required")
        candidate = (self._workdir / raw_path).resolve()
        if candidate != self._workdir and self._workdir not in candidate.parents:
            raise _ToolCallError(f"path escapes the repository: {raw_path}")
        relative_parts = candidate.relative_to(self._workdir).parts
        if any(part.lower() == GIT_DIRECTORY_NAME for part in relative_parts):
            raise _ToolCallError(f"path under {GIT_DIRECTORY_NAME} is not allowed: {raw_path}")
        return candidate

    def _user_message(self, ticket: Ticket, feedback: ReviewFeedback) -> str:
        parts = [f"Ticket {ticket.ticket_id}: {ticket.title}", ticket.description.strip()]
        feedback_block = _render_feedback(feedback)
        if feedback_block:
            parts.append(feedback_block)
        return "\n\n".join(part for part in parts if part)

    def _parse_verdict(self, content: str) -> StageOutcome:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise _VerdictError("review verdict is not valid JSON") from error
        if not isinstance(payload, dict):
            raise _VerdictError("review verdict must be a JSON object")
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise _VerdictError("review verdict summary must be a non-blank string")
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            raise _VerdictError("review verdict findings must be a list")
        findings = tuple(
            self._parse_finding(index, raw_finding)
            for index, raw_finding in enumerate(raw_findings)
        )
        return StageOutcome(summary=summary, findings=findings)

    def _parse_finding(self, index: int, raw_finding: object) -> Finding:
        prefix = f"findings[{index}]"
        if not isinstance(raw_finding, dict):
            raise _VerdictError(f"{prefix} must be a JSON object")
        evidence = raw_finding.get("evidence", "")
        if not isinstance(evidence, str):
            raise _VerdictError(f"{prefix}.evidence must be a string")
        ac = raw_finding.get("ac")
        if ac is not None and not isinstance(ac, str):
            raise _VerdictError(f"{prefix}.ac must be a string when present")
        try:
            return Finding(
                severity=_enum_value(
                    FindingSeverity, raw_finding.get("severity"), f"{prefix}.severity"
                ),
                category=_enum_value(
                    FindingCategory, raw_finding.get("category"), f"{prefix}.category"
                ),
                location=_text(raw_finding, "location", prefix),
                message=_text(raw_finding, "message", prefix),
                status=_enum_value(FindingStatus, raw_finding.get("status"), f"{prefix}.status"),
                evidence=evidence,
                ac=ac,
            )
        except InvalidFindingError as error:
            raise _VerdictError(f"{prefix}: {error}") from error
