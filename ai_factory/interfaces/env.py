"""Load a local .env file into os.environ (local development convenience)."""

import os
from pathlib import Path

VARIABLE_SEPARATOR = "="
COMMENT_PREFIX = "#"
QUOTE_CHARACTERS = ('"', "'")


def load_env_file(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE file, without overriding the environment.

    Args:
        path: Location of the .env file; silently ignored when absent.

    Raises:
        OSError: When the file exists but cannot be read.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(COMMENT_PREFIX) or VARIABLE_SEPARATOR not in line:
            continue
        key, value = line.split(VARIABLE_SEPARATOR, 1)
        os.environ.setdefault(
            key.strip(), value.strip().strip(QUOTE_CHARACTERS[0]).strip(QUOTE_CHARACTERS[1])
        )
