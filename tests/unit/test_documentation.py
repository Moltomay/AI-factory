"""Documentation contract tests: limits that must stay visible to operators."""

from pathlib import Path

README_PATH = Path(__file__).resolve().parents[2] / "README.md"


def test_spec06a_ac8_readme_documents_residual_risk() -> None:
    """AC8: the README states that 06a is a guardrail, not an OS sandbox."""
    content = README_PATH.read_text(encoding="utf-8").lower()

    assert "guardrail, not an os sandbox" in content
    assert "arbitrary code" in content
    assert "network" in content


def test_readme_documents_prerequisites_and_compatibility() -> None:
    """The README lists the services, variables and adapters operators must provide."""
    content = README_PATH.read_text(encoding="utf-8")

    assert "## Prerequisites" in content
    for variable in (
        "TRELLO_API_KEY",
        "TRELLO_TOKEN",
        "TRELLO_LIST_ID",
        "TRELLO_REVIEW_LIST_ID",
        "TRELLO_DONE_LIST_ID",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "GITHUB_TOKEN",
        "GITHUB_REPOSITORY",
        "FACTORY_WORKDIR",
    ):
        assert variable in content
    for service in ("Trello", "GitHub", "OpenRouter", "Jira", "Azure DevOps"):
        assert service in content
    assert "tool calling" in content.lower()
    assert "Compatibility matrix" in content


def test_spec07_ac11_readme_documents_three_agents() -> None:
    """AC11: three agents, one review, no target-repo digest, minimal gate."""
    content = README_PATH.read_text(encoding="utf-8")

    assert "## Agent team" in content
    for agent in ("Spec", "Coding", "Code Review"):
        assert agent in content
    assert "| Quality & Security |" not in content
    assert "integrated into Code Review" in content
    assert "factory-owned" in content
    assert "No repository digest is built" in content
    assert "`ruff check .` then `pytest`" in content
    assert "`sys.executable -m pytest -q`" in content
    assert "skipped only when the clone has no `tests/` directory" in content
    assert "06e" in content
    for term in (
        "blocker",
        "major",
        "minor",
        "evidence",
        "Approval is derived from the findings",
        "one corrective retry",
        "capped at 20",
    ):
        assert term in content
    assert "join the factory gate in" not in content
    assert "not read by the agents yet" not in content
