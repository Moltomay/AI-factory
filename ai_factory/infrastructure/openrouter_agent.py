"""OpenRouter code agent: LLM implementation of the CodeAgent port with a tool loop.

The model works inside the repository clone through a small, explicit tool set;
reviews are read-only and must return a JSON verdict. Every completion or tool
protocol failure is surfaced as ExternalServiceError so the pipeline stops loudly.
"""

import json
import shlex
import shutil
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.outcomes import StageOutcome
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
# --outp covers --output and its unambiguous abbreviations: the flag writes a
# file and could target .git.
GIT_REFUSED_FLAGS = (
    "--no-index",
    "--textconv",
    "--ext-diff",
    "--open-files-in-pager",
    "--outp",
)
GIT_DIRECTORY_NAME = ".git"
WINDOWS_EXECUTABLE_SUFFIX = ".exe"

DEVELOPER_PROMPT = (
    "You are the developer agent of an automated software factory.\n"
    "Implement the ticket in the repository located at the current working directory.\n"
    "Use the tools to inspect files, write the change and run checks.\n"
    "Keep the change minimal and limited to the repository.\n"
    "When the change is complete, reply with a short summary and stop calling tools."
)
QUALITY_PROMPT = (
    "You are the quality analyst agent of an automated software factory.\n"
    "Review the repository state against the ticket: correctness, tests and style.\n"
    "You can inspect files and run checks but must not modify anything.\n"
    "When done, reply with a single JSON object and nothing else: "
    '{"approved": true or false, "summary": "short verdict", "findings": ["..."]}'
)
REVIEWER_PROMPT = (
    "You are the final reviewer agent of an automated software factory.\n"
    "Review the repository state against the ticket as a strict senior reviewer.\n"
    "You can inspect files and run checks but must not modify anything.\n"
    "When done, reply with a single JSON object and nothing else: "
    '{"approved": true or false, "summary": "short verdict", "findings": ["..."]}'
)


class _ToolCallError(Exception):
    """Invalid tool call from the model; its message is fed back to the model."""


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
        if argument.startswith(GIT_REFUSED_FLAGS):
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

    def implement(self, ticket: Ticket, feedback: tuple[str, ...]) -> None:
        """Implement the ticket inside the workdir (writes allowed)."""
        self._run_agent(DEVELOPER_PROMPT, _IMPLEMENT_TOOLS, ticket, feedback)

    def quality_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        """Review the current repository state read-only and return the verdict."""
        content = self._run_agent(QUALITY_PROMPT, _READ_ONLY_TOOLS, ticket, feedback)
        return self._parse_verdict(content)

    def final_review(self, ticket: Ticket, feedback: tuple[str, ...]) -> StageOutcome:
        """Final read-only review of the repository state."""
        content = self._run_agent(REVIEWER_PROMPT, _READ_ONLY_TOOLS, ticket, feedback)
        return self._parse_verdict(content)

    def _run_agent(
        self,
        system_prompt: str,
        tools: list[dict[str, Any]],
        ticket: Ticket,
        feedback: tuple[str, ...],
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

    def _next_message(self, messages: list[Any], tools: list[dict[str, Any]]) -> Any:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
            )
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
        if not raw_path:
            raise _ToolCallError("path argument is required")
        candidate = (self._workdir / raw_path).resolve()
        if candidate != self._workdir and self._workdir not in candidate.parents:
            raise _ToolCallError(f"path escapes the repository: {raw_path}")
        relative_parts = candidate.relative_to(self._workdir).parts
        if any(part.lower() == GIT_DIRECTORY_NAME for part in relative_parts):
            raise _ToolCallError(f"path under {GIT_DIRECTORY_NAME} is not allowed: {raw_path}")
        return candidate

    def _user_message(self, ticket: Ticket, feedback: tuple[str, ...]) -> str:
        parts = [f"Ticket {ticket.ticket_id}: {ticket.title}", ticket.description.strip()]
        if feedback:
            parts.append("Findings from the previous failed attempt:")
            parts.extend(f"- {finding}" for finding in feedback)
        return "\n\n".join(part for part in parts if part)

    def _parse_verdict(self, content: str) -> StageOutcome:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ExternalServiceError("review verdict is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ExternalServiceError("review verdict must be a JSON object")
        approved = payload.get("approved")
        summary = payload.get("summary")
        findings = payload.get("findings", [])
        if (
            not isinstance(approved, bool)
            or not isinstance(summary, str)
            or not isinstance(findings, list)
        ):
            raise ExternalServiceError("review verdict has an invalid schema")
        if not all(isinstance(finding, str) for finding in findings):
            raise ExternalServiceError("review verdict findings must be strings")
        return StageOutcome(approved=approved, summary=summary, findings=tuple(findings))
