"""Behavior tests for the GitHub adapter, with fake git and HTTP (no network)."""

import base64
import subprocess
from pathlib import Path

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure import process as process_module
from ai_factory.infrastructure.github import GitHubVersionControl
from ai_factory.infrastructure.http import JsonHttpClient

REPOSITORY = "owner/sandbox"


class _FakeGit:
    """Records git invocations and replays a configured exit status."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.cwds: list[Path | None] = []
        self.envs: list[dict[str, str] | None] = []
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
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.cwds.append(cwd)
        self.envs.append(env)
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)

    @property
    def git_args(self) -> list[list[str]]:
        """Arguments after the executable and the auth header config."""
        return [command[3:] for command in self.commands]


def _make_vcs(tmp_path: Path) -> GitHubVersionControl:
    return GitHubVersionControl("test-secret-token", REPOSITORY, tmp_path / "clone")


def _install_fake_git(monkeypatch: pytest.MonkeyPatch) -> _FakeGit:
    fake_git = _FakeGit()
    monkeypatch.setattr(process_module.subprocess, "run", fake_git)
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


def test_spec03_ac3_clones_once_then_creates_branch_from_base(
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


def test_spec03_ac3_existing_clone_is_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC3: an existing clone is reused instead of cloned again."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)

    _make_vcs(tmp_path).create_branch("factory/42")

    assert fake_git.git_args == [
        ["fetch", "origin"],
        ["switch", "-C", "factory/42", "origin/main"],
    ]


def test_spec03_ac3_publish_commits_pushes_and_opens_pull_request(
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


def test_spec03_ac4_git_failure_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_spec03_ac4_http_failure_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4: a REST failure surfaces as ExternalServiceError."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    _install_fake_git(monkeypatch)
    _install_fake_http(monkeypatch, [ExternalServiceError("HTTP 422 for POST /pulls")])

    with pytest.raises(ExternalServiceError):
        _make_vcs(tmp_path).publish_pull_request("factory/42", "Title", "Body")


def test_spec06a_ac2_github_adapter_subprocess_gets_safe_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2: the git commands of the adapter run without the factory secrets."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    monkeypatch.setenv("TRELLO_TOKEN", "trello-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")

    _make_vcs(tmp_path).create_branch("factory/42")

    assert len(fake_git.envs) == 2
    for environment in fake_git.envs:
        assert environment is not None
        assert "TRELLO_TOKEN" not in environment
        assert "OPENROUTER_API_KEY" not in environment
        assert "GITHUB_TOKEN" not in environment
        assert "PATH" in environment


def test_spec06a_ac7_github_token_is_absent_from_child_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC7: the token is absent from the environment of every git command."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "test-secret-token")

    _make_vcs(tmp_path).create_branch("factory/42")

    for environment in fake_git.envs:
        assert environment is not None
        assert "GITHUB_TOKEN" not in environment
        assert "test-secret-token" not in environment.values()


def test_spec06a_ac7_github_token_stays_in_http_header_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC7: the token travels in the git auth header, not in the environment."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)

    _make_vcs(tmp_path).create_branch("factory/42")

    for command in fake_git.commands:
        header = command[2]
        assert header.startswith("http.extraHeader=AUTHORIZATION: basic ")
        credentials = base64.b64decode(header.rsplit(" ", 1)[-1]).decode()
        assert credentials == "x-access-token:test-secret-token"
        assert "test-secret-token" not in " ".join(command)


def test_spec06a_ac7_github_error_does_not_leak_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC7: a git failure message never contains the token."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    fake_git.returncode = 1
    fake_git.stderr = "fatal: auth failed for 'test-secret-token'"

    with pytest.raises(ExternalServiceError) as exc_info:
        _make_vcs(tmp_path).create_branch("factory/42")

    message = str(exc_info.value)
    assert "test-secret-token" not in message
    assert "***" in message


def test_spec06a_ac4_github_adapter_still_pushes_and_opens_pull_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC4: the read-only agent policy does not restrict the factory adapter."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    fake_git = _install_fake_git(monkeypatch)
    http_calls = _install_fake_http(
        monkeypatch, [{"html_url": "https://github.com/owner/sandbox/pull/1"}]
    )

    url = _make_vcs(tmp_path).publish_pull_request("factory/42", "Title", "Body")

    assert fake_git.git_args[-1] == ["push", "-u", "origin", "factory/42"]
    assert (http_calls[0][0], http_calls[0][1]) == ("POST", "/repos/owner/sandbox/pulls")
    assert url == "https://github.com/owner/sandbox/pull/1"
