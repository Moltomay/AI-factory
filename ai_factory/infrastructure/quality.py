"""Quality runner adapter: deterministic lint and test checks on the working copy.

Commands run in the repository clone, never through a shell. Missing tooling is an
infrastructure failure (ExternalServiceError); a red check is a normal `False`.
"""

import shutil
import sys
from pathlib import Path

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure.process import run_process

CHECK_TIMEOUT_SECONDS = 600
RUFF_ARGS = ("check", ".")
PYTEST_ARGS = ("-m", "pytest", "-q")
TESTS_DIRECTORY_NAME = "tests"
WINDOWS_EXECUTABLE_SUFFIX = ".exe"


class CommandQualityRunner:
    """QualityRunner running ruff and, when the clone has tests, pytest."""

    def __init__(self, workdir: Path, timeout_seconds: int = CHECK_TIMEOUT_SECONDS) -> None:
        """Store the clone location and the per-check timeout.

        Args:
            workdir: Repository clone the checks run in.
            timeout_seconds: Timeout applied to each check command.
        """
        self._workdir = Path(workdir)
        self._timeout_seconds = timeout_seconds

    def run_checks(self) -> bool:
        """Run lint and (when present) the test suite.

        Returns:
            True when every executed check passed, False otherwise.

        Raises:
            ExternalServiceError: When a check tool cannot be found or cannot run.
        """
        return self._run_ruff() and self._run_pytest()

    def _run_ruff(self) -> bool:
        completed = run_process(
            [_resolve_executable("ruff"), *RUFF_ARGS], self._workdir, self._timeout_seconds
        )
        return completed.returncode == 0

    def _run_pytest(self) -> bool:
        if not (self._workdir / TESTS_DIRECTORY_NAME).is_dir():
            return True
        completed = run_process(
            [sys.executable, *PYTEST_ARGS], self._workdir, self._timeout_seconds
        )
        return completed.returncode == 0


def _resolve_executable(name: str) -> str:
    """Find a tool installed next to the running interpreter, then on PATH.

    Args:
        name: Executable name without extension, e.g. "ruff".

    Returns:
        Absolute path of the executable.

    Raises:
        ExternalServiceError: When the executable cannot be found.
    """
    scripts_directory = Path(sys.executable).parent
    for candidate_name in (f"{name}{WINDOWS_EXECUTABLE_SUFFIX}", name):
        candidate = scripts_directory / candidate_name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found is None:
        raise ExternalServiceError(f"{name} executable not found")
    return found
