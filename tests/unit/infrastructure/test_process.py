"""Behavior tests for the shared process helper, with a fake subprocess (no real git)."""

import subprocess
from pathlib import Path

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import process as process_module
from ai_factory.infrastructure.process import run_process


class _FakeRun:
    """Replays a configured outcome and records the environment of the child."""

    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.envs: list[dict[str, str] | None] = []

    def __call__(
        self,
        command: list[str],
        cwd: Path | None = None,
        capture_output: bool = False,
        text: bool = False,
        timeout: int | None = None,
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> object:
        self.envs.append(env)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _install_fake_run(monkeypatch: pytest.MonkeyPatch, outcome: object) -> _FakeRun:
    fake_run = _FakeRun(outcome)
    monkeypatch.setattr(process_module.subprocess, "run", fake_run)
    return fake_run


def test_command_result_is_returned_as_is(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Non-zero exit codes are returned to the caller, not raised."""
    completed = subprocess.CompletedProcess(["git"], 3, "out", "err")
    _install_fake_run(monkeypatch, completed)

    result = run_process(["git", "status"], tmp_path, 10)

    assert (result.returncode, result.stdout, result.stderr) == (3, "out", "err")


def test_os_error_becomes_external_service_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A command that cannot start raises ExternalServiceError."""
    _install_fake_run(monkeypatch, OSError("missing executable"))

    with pytest.raises(ExternalServiceError):
        run_process(["missing"], tmp_path, 10)


def test_timeout_becomes_external_service_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A command that times out raises ExternalServiceError."""
    _install_fake_run(monkeypatch, subprocess.TimeoutExpired(["slow"], 10))

    with pytest.raises(ExternalServiceError):
        run_process(["slow"], tmp_path, 10)


def test_spec06a_ac1_safe_environment_removes_secrets_and_unknown_variables(
    tmp_path: Path,
) -> None:
    """AC1: only allowlisted variables survive, whatever their origin."""
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/factory",
        "TRELLO_TOKEN": "trello-secret",
        "OPENROUTER_API_KEY": "openrouter-secret",
        "GITHUB_TOKEN": "github-secret",
        "FACTORY_WORKDIR": str(tmp_path / "work"),
        "UNRELATED_VARIABLE": "value",
        "trello_token": "lowercase-secret",
    }

    environment = process_module.build_safe_environment(source)

    assert environment == {"PATH": "/usr/bin", "HOME": "/home/factory"}


def test_spec06a_ac1_safe_environment_keeps_required_system_variables(
    tmp_path: Path,
) -> None:
    """AC1: the child keeps the system variables it needs to start."""
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/factory",
        "TEMP": str(tmp_path),
        "LANG": "C.UTF-8",
        "SYSTEMROOT": "C:\\Windows",
        "PATHEXT": ".EXE;.CMD",
    }

    environment = process_module.build_safe_environment(source)

    assert environment["PATH"] == "/usr/bin"
    assert environment["HOME"] == "/home/factory"
    assert environment["TEMP"] == str(tmp_path)
    assert environment["LANG"] == "C.UTF-8"
    assert environment["SYSTEMROOT"] == "C:\\Windows"
    assert environment["PATHEXT"] == ".EXE;.CMD"


def test_spec06a_ac1_run_process_uses_safe_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC1: run_process never passes the factory environment to the child."""
    monkeypatch.setenv("TRELLO_TOKEN", "trello-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    fake_run = _install_fake_run(monkeypatch, subprocess.CompletedProcess(["git"], 0, "", ""))

    run_process(["git", "status"], tmp_path, 10)

    environment = fake_run.envs[0]
    assert environment is not None
    assert "TRELLO_TOKEN" not in environment
    assert "OPENROUTER_API_KEY" not in environment
    assert "PATH" in environment
