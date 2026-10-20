"""Subprocess helper shared by the infrastructure adapters.

Commands are passed as a structured argument list (never through a shell), so
values coming from tickets or the model cannot be injected into a command line.
"""

import subprocess
from pathlib import Path

from ai_factory.domain.errors import ExternalServiceError


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
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExternalServiceError(f"could not run {command[0]}") from error
