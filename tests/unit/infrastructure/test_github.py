"""Behavior tests for the GitHub adapter, with fake git and HTTP (no network)."""

import subprocess
from pathlib import Path

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import github as github_module
from ai_factory.infrastructure.github import GitHubVersionControl
from ai_factory.infrastructure.http import JsonHttpClient

REPOSITORY = "owner/sandbox"


class _FakeGit:
    """Records git invocations and replays a configured exit status."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.cwds: list[Path | None] = []
        self.returncode = 0
        self.stderr = ""

    def __call__(
        self,
        command: list[str],
        cwd: Path | None = None,
        capture_output: bool = False,
        text: bool = False,
        timeout: int | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.cwds.append(cwd)
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)

    @property
    def git_args(self) -> list[list[str]]:
        """Arguments after the executable and the auth header config."""
        return [command[3:] for command in self.commands]


def _make_vcs(tmp_path: Path) -> GitHubVersionControl:
    return GitHubVersionControl("test-secret-token", REPOSITORY, tmp_path / "clone")


def _install_fake_git(monkeypatch: pytest.MonkeyPatch) -> _FakeGit:
    fake_git = _FakeGit()
    monkeypatch.setattr(github_module.subprocess, "run", fake_git)
    return fake_git


def _install_fake_http(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object]
) -> list[tuple[str, str, dict[str, str] | None, dict[str, object] | None]]:
    calls: list[tuple[str, str, dict[str, str] | None, dict[str, object] | None]] = []
    queue = list(outcomes)

    def fake_request_json(
        self: JsonHttpClient,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        calls.append((method, path, params, body))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(JsonHttpClient, "request_json", fake_request_json)
    return calls


def test_ac3_clones_once_then_creates_branch_from_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: the clone is created on first use, then the branch comes from origin/main."""
    fake_git = _install_fake_git(monkeypatch)
    version_control = _make_vcs(tmp_path)

    version_control.create_branch("factory/42")

    clone_args = fake_git.git_args[0]
    assert clone_args == [
        "clone",
        "https://github.com/owner/sandbox.git",
        str(tmp_path / "clone"),
    ]
    assert fake_git.cwds[0] == tmp_path
    assert "x-access-token:" not in " ".join(clone_args)
    assert fake_git.git_args[1] == ["fetch", "origin"]
    assert fake_git.git_args[2] == ["switch", "-C", "factory/42", "origin/main"]


def test_ac3_existing_clone_is_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC3: an existing clone is reused instead of cloned again."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)

    _make_vcs(tmp_path).create_branch("factory/42")

    assert fake_git.git_args == [
        ["fetch", "origin"],
        ["switch", "-C", "factory/42", "origin/main"],
    ]


def test_ac3_publish_commits_pushes_and_opens_pull_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: publish commits everything, pushes and returns the pull request URL."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    http_calls = _install_fake_http(
        monkeypatch, [{"html_url": "https://github.com/owner/sandbox/pull/1"}]
    )
    version_control = _make_vcs(tmp_path)

    url = version_control.publish_pull_request("factory/42", "Add hello.txt", "Ticket body")

    assert url == "https://github.com/owner/sandbox/pull/1"
    assert fake_git.git_args == [
        ["add", "-A"],
        [
            "-c",
            "user.name=AI Factory",
            "-c",
            "user.email=ai-factory@users.noreply.github.com",
            "commit",
            "-m",
            "Add hello.txt",
        ],
        ["push", "-u", "origin", "factory/42"],
    ]
    method, path, _, body = http_calls[0]
    assert (method, path) == ("POST", "/repos/owner/sandbox/pulls")
    assert body == {
        "title": "Add hello.txt",
        "body": "Ticket body",
        "head": "factory/42",
        "base": "main",
    }


def test_ac4_git_failure_is_scrubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC4: a git failure raises ExternalServiceError without leaking the token."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    fake_git.returncode = 1
    fake_git.stderr = "fatal: auth failed for 'test-secret-token'"

    with pytest.raises(ExternalServiceError) as exc_info:
        _make_vcs(tmp_path).create_branch("factory/42")

    message = str(exc_info.value)
    assert "git fetch failed" in message
    assert "test-secret-token" not in message
    assert "***" in message


def test_ac4_http_failure_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC4: a REST failure surfaces as ExternalServiceError."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    _install_fake_git(monkeypatch)
    _install_fake_http(monkeypatch, [ExternalServiceError("HTTP 422 for POST /pulls")])

    with pytest.raises(ExternalServiceError):
        _make_vcs(tmp_path).publish_pull_request("factory/42", "Title", "Body")
