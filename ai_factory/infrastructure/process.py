"""Subprocess helper shared by the infrastructure adapters.

Commands are passed as a structured argument list (never through a shell), so
values coming from tickets or the model cannot be injected into a command line.
Child processes get a sanitized environment: only the system variables they need
to start and to find the tooling are kept, so factory secrets never leak to them.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ai_factory.domain.errors import ExternalServiceError

SAFE_ENVIRONMENT_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "USER",
        "LOGNAME",
        "SHELL",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "COMMONPROGRAMFILES",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
    }
)
SECRET_ENVIRONMENT_PREFIXES = ("TRELLO_", "OPENROUTER_", "GITHUB_", "FACTORY_")


def build_safe_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the environment given to every child process.

    The rule is default deny: only the system variables needed to start a tool
    and to resolve it on PATH are kept. Factory secrets and unknown variables
    are dropped, so a command run by the model cannot read them.

    Args:
        source: Environment to filter; os.environ when omitted.

    Returns:
        A new dict with only the approved variables.
    """
    environment = os.environ if source is None else source
    return {
        name: value
        for name, value in environment.items()
        if name.upper() in SAFE_ENVIRONMENT_NAMES
        and not name.upper().startswith(SECRET_ENVIRONMENT_PREFIXES)
    }


def run_process(
    command: list[str], cwd: Path, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    """Run one command and capture its output.

    Args:
        command: Executable followed by its arguments; never a shell string.
        cwd: Working directory of the process.
        timeout_seconds: Hard timeout for the command.

    Returns:
        The completed process; non-zero exit codes are returned, not raised.

    Raises:
        ExternalServiceError: When the command cannot start or times out.
    """
    try:
        # Structured argv without a shell: untrusted values cannot be injected.
        return subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=build_safe_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExternalServiceError(f"could not run {command[0]}") from error
