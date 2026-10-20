"""GitHub adapter: VersionControl backed by the git CLI and the GitHub REST API."""

import base64
import shutil
import subprocess
from pathlib import Path

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.infrastructure.http import HTTP_TIMEOUT_SECONDS, JsonHttpClient

API_BASE_URL = "https://api.github.com"
DEFAULT_BASE_BRANCH = "main"
GIT_TIMEOUT_SECONDS = 300
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

    def _run_git(self, *args: str, cwd: Path | None = None) -> None:
        command = [self._git, "-c", self._auth_header(), *args]
        try:
            # Structured argv without a shell: untrusted values cannot be injected.
            completed = subprocess.run(  # noqa: S603
                command,
                cwd=cwd or self._workdir,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ExternalServiceError(f"git {args[0]} could not run") from error
        if completed.returncode != 0:
            raise ExternalServiceError(
                f"git {args[0]} failed: {self._scrub(completed.stderr.strip())}"
            )

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
