"""Behavior tests for the quality runner adapter, with a fake process (no network)."""

import subprocess
import sys
from pathlib import Path

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import process as process_module
from ai_factory.infrastructure import quality as quality_module
from ai_factory.infrastructure.quality import CommandQualityRunner


class _FakeRun:
    """Records commands and replays configured exit codes per executable."""

    def __init__(self, returncodes: list[int]) -> None:
        self.commands: list[list[str]] = []
        self.cwds: list[Path] = []
        self._returncodes = list(returncodes)

    def __call__(self, command: list[str], cwd: Path, timeout_seconds: int) -> object:
        self.commands.append(list(command))
        self.cwds.append(cwd)
        return subprocess.CompletedProcess(command, self._returncodes.pop(0), "", "")


def _install_fake_run(monkeypatch: pytest.MonkeyPatch, returncodes: list[int]) -> _FakeRun:
    fake_run = _FakeRun(returncodes)
    monkeypatch.setattr(quality_module, "run_process", fake_run)
    return fake_run


def test_spec04_ac6_lint_passes_and_tests_are_skipped_without_tests_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC6: without a tests directory only ruff runs, and its success approves."""
    fake_run = _install_fake_run(monkeypatch, [0])

    assert CommandQualityRunner(tmp_path).run_checks() is True

    assert Path(fake_run.commands[0][0]).name in {"ruff", "ruff.exe"}
    assert fake_run.commands[0][1:] == ["check", "."]
    assert fake_run.cwds == [tmp_path]


def test_spec04_ac6_lint_and_tests_run_when_tests_directory_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC6: a tests directory triggers the test suite after the lint."""
    (tmp_path / "tests").mkdir()
    fake_run = _install_fake_run(monkeypatch, [0, 0])

    assert CommandQualityRunner(tmp_path).run_checks() is True

    assert fake_run.commands[1] == [sys.executable, "-m", "pytest", "-q"]


def test_spec04_ac6_red_lint_rejects_without_running_tests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC6: a failing lint rejects the change and skips the tests."""
    (tmp_path / "tests").mkdir()
    fake_run = _install_fake_run(monkeypatch, [1])

    assert CommandQualityRunner(tmp_path).run_checks() is False

    assert len(fake_run.commands) == 1


def test_spec04_ac6_red_tests_reject(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC6: failing tests reject the change."""
    (tmp_path / "tests").mkdir()
    _install_fake_run(monkeypatch, [0, 1])

    assert CommandQualityRunner(tmp_path).run_checks() is False


def test_spec04_ac6_missing_executable_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC6: a missing check tool raises ExternalServiceError."""
    monkeypatch.setattr(quality_module.sys, "executable", str(tmp_path / "missing" / "python.exe"))
    monkeypatch.setattr(quality_module.shutil, "which", lambda name: None)

    with pytest.raises(ExternalServiceError, match="ruff"):
        CommandQualityRunner(tmp_path).run_checks()


class _FakeSubprocess:
    """Records the environment that run_process gives to each child."""

    def __init__(self, returncodes: list[int]) -> None:
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self._returncodes = list(returncodes)

    def __call__(
        self,
        command: list[str],
        cwd: Path | None = None,
        capture_output: bool = False,
        text: bool = False,
        timeout: int | None = None,
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.envs.append(env)
        return subprocess.CompletedProcess(command, self._returncodes.pop(0), "", "")


def test_spec06a_ac2_quality_runner_subprocess_gets_safe_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2: the deterministic checks never receive the factory secrets."""
    (tmp_path / "tests").mkdir()
    monkeypatch.setenv("TRELLO_TOKEN", "trello-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    fake_process = _FakeSubprocess([0, 0])
    monkeypatch.setattr(process_module.subprocess, "run", fake_process)

    assert CommandQualityRunner(tmp_path).run_checks() is True

    assert len(fake_process.envs) == 2
    for environment in fake_process.envs:
        assert environment is not None
        assert "TRELLO_TOKEN" not in environment
        assert "OPENROUTER_API_KEY" not in environment
        assert "GITHUB_TOKEN" not in environment
        assert "PATH" in environment
