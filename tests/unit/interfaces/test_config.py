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
    "TRELLO_REVIEW_LIST_ID": "list-2",
    "TRELLO_DONE_LIST_ID": "list-3",
    "OPENROUTER_API_KEY": "test-openrouter-key",
    "OPENROUTER_MODEL": "vendor/model:free",
    "GITHUB_TOKEN": "test-github-token",
    "GITHUB_REPOSITORY": "owner/sandbox",
}


def test_spec04_ac1_complete_environment_builds_configuration(tmp_path: Path) -> None:
    """AC1: every value is carried over and the clone lives under the workdir."""
    workdir = tmp_path / "work"

    config = load_config({**COMPLETE_ENV, "FACTORY_WORKDIR": str(workdir)})

    assert config.trello_api_key == "test-trello-key"
    assert config.github_repository == "owner/sandbox"
    assert config.openrouter_model == "vendor/model:free"
    assert config.workdir == workdir
    assert config.clone_directory == workdir / "clone"


def test_spec04_ac1_missing_variables_are_named_without_values() -> None:
    """AC1: the error lists the missing names only, never a value."""
    incomplete = {key: value for key, value in COMPLETE_ENV.items() if key != "GITHUB_TOKEN"}

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(incomplete)

    message = str(exc_info.value)
    assert "GITHUB_TOKEN" in message
    assert "test-trello-key" not in message


def test_spec04_ac1_blank_variable_counts_as_missing() -> None:
    """AC1: a blank value is rejected like an absent variable."""
    with pytest.raises(ConfigurationError, match="OPENROUTER_MODEL"):
        load_config({**COMPLETE_ENV, "OPENROUTER_MODEL": "   "})


def test_spec04_ac1_default_workdir_lives_in_the_temp_directory() -> None:
    """AC1: without FACTORY_WORKDIR the workdir defaults under the temp directory."""
    config = load_config(COMPLETE_ENV)

    assert config.workdir == Path(tempfile.gettempdir()) / DEFAULT_WORKDIR_NAME


def test_spec06b_ac1_complete_environment_carries_the_three_list_ids() -> None:
    """AC1: the review and done lists are exposed next to the processing list."""
    config = load_config(COMPLETE_ENV)

    assert config.trello_list_id == "list-1"
    assert config.trello_review_list_id == "list-2"
    assert config.trello_done_list_id == "list-3"


def test_spec06b_ac1_missing_review_list_is_named_without_values() -> None:
    """AC1: a missing review list is reported by name only."""
    incomplete = {
        key: value for key, value in COMPLETE_ENV.items() if key != "TRELLO_REVIEW_LIST_ID"
    }

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(incomplete)

    message = str(exc_info.value)
    assert "TRELLO_REVIEW_LIST_ID" in message
    assert "test-trello-key" not in message


def test_spec06b_ac1_duplicate_list_ids_are_rejected() -> None:
    """AC1: the three lists must be distinct, otherwise a status maps to two lists."""
    with pytest.raises(ConfigurationError) as exc_info:
        load_config({**COMPLETE_ENV, "TRELLO_DONE_LIST_ID": "list-2"})

    message = str(exc_info.value)
    assert "TRELLO_LIST_ID" in message
    assert "TRELLO_REVIEW_LIST_ID" in message
    assert "TRELLO_DONE_LIST_ID" in message
    assert "list-2" not in message
