"""Documentation contract tests: limits that must stay visible to operators."""

from pathlib import Path

README_PATH = Path(__file__).resolve().parents[2] / "README.md"


def test_spec06a_ac8_readme_documents_residual_risk() -> None:
    """AC8: the README states that 06a is a guardrail, not an OS sandbox."""
    content = README_PATH.read_text(encoding="utf-8").lower()

    assert "guardrail, not an os sandbox" in content
    assert "arbitrary code" in content
    assert "network" in content
