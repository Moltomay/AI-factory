"""Factory configuration loaded from the environment."""

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKDIR_NAME = "factory-workdir"
CLONE_DIRECTORY_NAME = "clone"
REQUIRED_VARIABLES = (
    "TRELLO_API_KEY",
    "TRELLO_TOKEN",
    "TRELLO_LIST_ID",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
)


class ConfigurationError(Exception):
    """Raised when required environment variables are missing or blank."""


@dataclass(frozen=True)
class FactoryConfig:
    """Validated runtime configuration, independent of os.environ.

    Attributes:
        trello_api_key: Trello API key.
        trello_token: Trello user token.
        trello_list_id: List holding the tickets to process.
        openrouter_api_key: OpenRouter API key.
        openrouter_model: OpenRouter model identifier.
        github_token: GitHub token allowed to push and open pull requests.
        github_repository: Target repository in owner/name form.
        workdir: Root directory of the factory's local state.
    """

    trello_api_key: str
    trello_token: str
    trello_list_id: str
    openrouter_api_key: str
    openrouter_model: str
    github_token: str
    github_repository: str
    workdir: Path

    @property
    def clone_directory(self) -> Path:
        """Local clone shared by the code agent, the checks and the version control."""
        return self.workdir / CLONE_DIRECTORY_NAME


def load_config(environ: Mapping[str, str]) -> FactoryConfig:
    """Build the configuration from an environment mapping.

    Args:
        environ: Environment variables (os.environ in production).

    Returns:
        The validated configuration.

    Raises:
        ConfigurationError: When required variables are missing or blank; the
            message lists names only, never values.
    """
    missing = [name for name in REQUIRED_VARIABLES if not environ.get(name, "").strip()]
    if missing:
        raise ConfigurationError(f"Missing configuration variables: {', '.join(missing)}")
    raw_workdir = environ.get("FACTORY_WORKDIR", "").strip()
    return FactoryConfig(
        trello_api_key=environ["TRELLO_API_KEY"].strip(),
        trello_token=environ["TRELLO_TOKEN"].strip(),
        trello_list_id=environ["TRELLO_LIST_ID"].strip(),
        openrouter_api_key=environ["OPENROUTER_API_KEY"].strip(),
        openrouter_model=environ["OPENROUTER_MODEL"].strip(),
        github_token=environ["GITHUB_TOKEN"].strip(),
        github_repository=environ["GITHUB_REPOSITORY"].strip(),
        workdir=(
            Path(raw_workdir) if raw_workdir else Path(tempfile.gettempdir()) / DEFAULT_WORKDIR_NAME
        ),
    )
