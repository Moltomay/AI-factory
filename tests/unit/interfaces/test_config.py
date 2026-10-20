"""Behavior tests for the configuration loader (no network)."""

import tempfile
from pathlib import Path

import pytest

from ai_factory.interfaces.config import (
    DEFAULT_WORKDIR_NAME,
    ConfigurationError,
    load_config,
)

COMPLETE_ENV = {
    "TRELLO_API_KEY": "test-trello-key",
    "TRELLO_TOKEN": "test-trello-token",
    "TRELLO_LIST_ID": "list-1",
    "OPENROUTER_API_KEY": "test-openrouter-key",
    "OPENROUTER_MODEL": "vendor/model:free",
    "GITHUB_TOKEN": "test-github-token",
    "GITHUB_REPOSITORY": "owner/sandbox",
}


def test_ac1_complete_environment_builds_configuration(tmp_path: Path) -> None:
    """AC1: every value is carried over and the clone lives under the workdir."""
    workdir = tmp_path / "work"

    config = load_config({**COMPLETE_ENV, "FACTORY_WORKDIR": str(workdir)})

    assert config.trello_api_key == "test-trello-key"
    assert config.github_repository == "owner/sandbox"
    assert config.openrouter_model == "vendor/model:free"
    assert config.workdir == workdir
    assert config.clone_directory == workdir / "clone"


def test_ac1_missing_variables_are_named_without_values() -> None:
    """AC1: the error lists the missing names only, never a value."""
    incomplete = {key: value for key, value in COMPLETE_ENV.items() if key != "GITHUB_TOKEN"}

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(incomplete)

    message = str(exc_info.value)
    assert "GITHUB_TOKEN" in message
    assert "test-trello-key" not in message


def test_ac1_blank_variable_counts_as_missing() -> None:
    """AC1: a blank value is rejected like an absent variable."""
    with pytest.raises(ConfigurationError, match="OPENROUTER_MODEL"):
        load_config({**COMPLETE_ENV, "OPENROUTER_MODEL": "   "})


def test_ac1_default_workdir_lives_in_the_temp_directory() -> None:
    """AC1: without FACTORY_WORKDIR the workdir defaults under the temp directory."""
    config = load_config(COMPLETE_ENV)

    assert config.workdir == Path(tempfile.gettempdir()) / DEFAULT_WORKDIR_NAME
