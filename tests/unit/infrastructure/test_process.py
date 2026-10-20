"""Behavior tests for the shared process helper, with a fake subprocess (no real git)."""

import subprocess
from pathlib import Path

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import process as process_module
from ai_factory.infrastructure.process import run_process


def _install_fake_run(monkeypatch: pytest.MonkeyPatch, outcome: object) -> None:
    def fake_run(
        command: list[str],
        cwd: Path | None = None,
        capture_output: bool = False,
        text: bool = False,
        timeout: int | None = None,
        check: bool = False,
    ) -> object:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(process_module.subprocess, "run", fake_run)


def test_command_result_is_returned_as_is(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Non-zero exit codes are returned to the caller, not raised."""
    completed = subprocess.CompletedProcess(["git"], 3, "out", "err")
    _install_fake_run(monkeypatch, completed)

    result = run_process(["git", "status"], tmp_path, 10)

    assert (result.returncode, result.stdout, result.stderr) == (3, "out", "err")


def test_os_error_becomes_external_service_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4: a command that cannot start raises ExternalServiceError."""
    _install_fake_run(monkeypatch, OSError("missing executable"))

    with pytest.raises(ExternalServiceError):
        run_process(["missing"], tmp_path, 10)


def test_timeout_becomes_external_service_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4: a command that times out raises ExternalServiceError."""
    _install_fake_run(monkeypatch, subprocess.TimeoutExpired(["slow"], 10))

    with pytest.raises(ExternalServiceError):
        run_process(["slow"], tmp_path, 10)
