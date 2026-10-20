"""Real GitHub integration test: runs only with local credentials present (AC8)."""

import os
import uuid

import pytest

from ai_factory.infrastructure.github import GitHubVersionControl
from ai_factory.infrastructure.http import JsonHttpClient

pytestmark = pytest.mark.integration

_REQUIRED_ENV = ("GITHUB_TOKEN", "GITHUB_REPOSITORY")
API_BASE_URL = "https://api.github.com"


@pytest.mark.skipif(
    any(not os.environ.get(name) for name in _REQUIRED_ENV),
    reason="GitHub credentials missing from the environment",
)
def test_ac8_real_branch_and_pull_request_round_trip(tmp_path) -> None:
    """AC8: clone, branch, commit, push, open a PR, then clean up on the sandbox."""
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    marker = uuid.uuid4().hex[:12]
    branch = f"factory/integration-{marker}"
    version_control = GitHubVersionControl(token, repository, tmp_path / "clone")

    version_control.create_branch(branch)
    changed_file = tmp_path / "clone" / f"integration-test-{marker}.txt"
    changed_file.write_text("hello from the real integration test\n", encoding="utf-8")

    url = version_control.publish_pull_request(
        branch, f"[AI Factory integration] {marker}", "Automated integration test PR."
    )

    assert "/pull/" in url
    client = JsonHttpClient(API_BASE_URL)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    number = url.rsplit("/", 1)[-1]
    pull_request = client.request_json(
        "GET", f"/repos/{repository}/pulls/{number}", headers=headers
    )
    assert pull_request["state"] == "open"

    client.request_json(
        "PATCH", f"/repos/{repository}/pulls/{number}", body={"state": "closed"}, headers=headers
    )
    client.request_json("DELETE", f"/repos/{repository}/git/refs/heads/{branch}", headers=headers)
