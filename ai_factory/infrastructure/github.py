"""GitHub adapter: VersionControl backed by the git CLI and the GitHub REST API."""

import base64
import shutil
from pathlib import Path
from subprocess import CompletedProcess

from ai_factory.application.ports import PullRequestState
from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure.http import HTTP_TIMEOUT_SECONDS, JsonHttpClient
from ai_factory.infrastructure.process import run_process

API_BASE_URL = "https://api.github.com"
DEFAULT_BASE_BRANCH = "main"
GIT_TIMEOUT_SECONDS = 300
GIT_NO_MATCH_STATUS = 2
GIT_AUTH_USERNAME = "x-access-token"
COMMIT_AUTHOR_NAME = "AI Factory"
COMMIT_AUTHOR_EMAIL = "ai-factory@users.noreply.github.com"
SCRUBBED = "***"
GIT_EXECUTABLE = shutil.which("git")


class GitHubVersionControl:
    """VersionControl backed by a local git clone and the GitHub REST API.

    The clone lives in `workdir` and is created on first use. Git authentication
    uses a per-command `http.extraHeader`, so the token is never written to
    `.git/config`; error messages are scrubbed of the token.
    """

    def __init__(
        self,
        token: str,
        repository: str,
        workdir: Path,
        base_branch: str = DEFAULT_BASE_BRANCH,
        api_base_url: str = API_BASE_URL,
        timeout_seconds: int = GIT_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the adapter.

        Args:
            token: GitHub token allowed to push and open pull requests.
            repository: Target repository in owner/name form.
            workdir: Local clone location; created on first use.
            base_branch: Branch the pull request targets.
            api_base_url: REST API root, overridable for tests.
            timeout_seconds: Timeout for each git command.
        """
        self._token = token
        self._repository = repository
        self._workdir = Path(workdir)
        self._base_branch = base_branch
        self._client = JsonHttpClient(api_base_url, HTTP_TIMEOUT_SECONDS)
        self._timeout_seconds = timeout_seconds
        if GIT_EXECUTABLE is None:
            raise ExternalServiceError("git executable not found on PATH")
        self._git = GIT_EXECUTABLE

    def create_branch(self, branch_name: str) -> None:
        """Create (or reset) the working branch from the latest base branch."""
        self._ensure_clone()
        self._run_git("fetch", "origin")
        self._run_git("switch", "-C", branch_name, f"origin/{self._base_branch}")

    def publish_pull_request(self, branch_name: str, title: str, body: str) -> str:
        """Commit the working copy, push the branch and open the pull request.

        Args:
            branch_name: Branch holding the change.
            title: Pull request title, also used as the commit message.
            body: Pull request description.

        Returns:
            The URL of the opened pull request.
        """
        self._run_git("add", "-A")
        self._run_git(
            "-c",
            f"user.name={COMMIT_AUTHOR_NAME}",
            "-c",
            f"user.email={COMMIT_AUTHOR_EMAIL}",
            "commit",
            "-m",
            title,
        )
        self._run_git("push", "-u", "origin", branch_name)
        response = self._client.request_json(
            "POST",
            f"/repos/{self._repository}/pulls",
            body={
                "title": title,
                "body": body,
                "head": branch_name,
                "base": self._base_branch,
            },
            headers=self._api_headers(),
        )
        return response["html_url"]

    def pull_request_state(self, branch_name: str) -> PullRequestState:
        """Return what happened to the pull request opened from the branch.

        Several pull requests may exist for one branch; a merge wins over an
        open one, which wins over a closed one.

        Args:
            branch_name: Branch the pull request was opened from.

        Returns:
            The pull request state, or NOT_FOUND when no pull request exists.
        """
        owner = self._repository.split("/", 1)[0]
        pull_requests = self._client.request_json(
            "GET",
            f"/repos/{self._repository}/pulls",
            {
                "head": f"{owner}:{branch_name}",
                "state": "all",
                "base": self._base_branch,
            },
            headers=self._api_headers(),
        )
        return _pull_request_state(pull_requests)

    def delete_branch(self, branch_name: str) -> None:
        """Delete the remote branch, treating an absent branch as already done.

        A closed pull request may be reconciled again after its branch was
        deleted manually; that must not keep the card stuck in In Review.

        Args:
            branch_name: Branch to delete from the remote repository.
        """
        self._ensure_clone()
        if not self._remote_branch_exists(branch_name):
            return
        self._run_git("push", "origin", "--delete", branch_name)

    def _ensure_clone(self) -> None:
        if (self._workdir / ".git").exists():
            return
        self._workdir.parent.mkdir(parents=True, exist_ok=True)
        self._run_git(
            "clone",
            f"https://github.com/{self._repository}.git",
            str(self._workdir),
            cwd=self._workdir.parent,
        )

    def _remote_branch_exists(self, branch_name: str) -> bool:
        completed = self._run_git_command(
            "ls-remote", "--exit-code", "--heads", "origin", branch_name
        )
        if completed.returncode == 0:
            return True
        if completed.returncode == GIT_NO_MATCH_STATUS:
            return False
        raise ExternalServiceError(f"git ls-remote failed: {self._scrub(completed.stderr.strip())}")

    def _run_git(self, *args: str, cwd: Path | None = None) -> None:
        completed = self._run_git_command(*args, cwd=cwd)
        if completed.returncode != 0:
            raise ExternalServiceError(
                f"git {args[0]} failed: {self._scrub(completed.stderr.strip())}"
            )

    def _run_git_command(self, *args: str, cwd: Path | None = None) -> CompletedProcess[str]:
        command = [self._git, "-c", self._auth_header(), *args]
        return run_process(command, cwd or self._workdir, self._timeout_seconds)

    def _auth_header(self) -> str:
        credentials = base64.b64encode(f"{GIT_AUTH_USERNAME}:{self._token}".encode()).decode()
        return f"http.extraHeader=AUTHORIZATION: basic {credentials}"

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
        }

    def _scrub(self, text: str) -> str:
        scrubbed = text.replace(self._token, SCRUBBED)
        return scrubbed.replace(self._auth_header(), SCRUBBED)


def _pull_request_state(pull_requests: list[dict[str, object]]) -> PullRequestState:
    """Map the pull requests of one branch to a single lifecycle state.

    Args:
        pull_requests: Payload of GET /repos/{repo}/pulls for one branch.

    Returns:
        MERGED if any pull request was merged, otherwise OPEN if any is open,
        otherwise CLOSED if any exists, otherwise NOT_FOUND.
    """
    if any(pull_request["merged_at"] for pull_request in pull_requests):
        return PullRequestState.MERGED
    states = {pull_request["state"] for pull_request in pull_requests}
    if "open" in states:
        return PullRequestState.OPEN
    if states:
        return PullRequestState.CLOSED
    return PullRequestState.NOT_FOUND
