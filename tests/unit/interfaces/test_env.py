"""Behavior tests for the .env loader (no network)."""

import os
from pathlib import Path

import pytest

from ai_factory.interfaces.env import load_env_file

ALPHA = "AI_FACTORY_TEST_ALPHA"
BETA = "AI_FACTORY_TEST_BETA"


def _clear_test_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ALPHA, BETA):
        monkeypatch.delenv(name, raising=False)


def test_spec04_ac2_values_are_loaded_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2: keys are loaded, comments/blanks ignored, quotes stripped."""
    _clear_test_variables(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f'# local credentials\n\n{ALPHA}=first\n{BETA}="quoted value"\n',
        encoding="utf-8",
    )

    load_env_file(env_file)

    assert os.environ[ALPHA] == "first"
    assert os.environ[BETA] == "quoted value"


def test_spec04_ac2_existing_environment_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2: a variable already defined in the environment is never overridden."""
    monkeypatch.setenv(ALPHA, "from-environment")
    env_file = tmp_path / ".env"
    env_file.write_text(f"{ALPHA}=from-file\n", encoding="utf-8")

    load_env_file(env_file)

    assert os.environ[ALPHA] == "from-environment"


def test_spec04_ac2_missing_file_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2: an absent .env file is a no-op."""
    _clear_test_variables(monkeypatch)

    load_env_file(tmp_path / "absent.env")

    assert ALPHA not in os.environ
