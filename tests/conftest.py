"""Pytest configuration: load the local .env file for the real integration tests.

The gitignored AI-factory/.env file provides credentials for the tests marked
`integration`. Variables already defined in the environment always win, so CI
(no .env) keeps running the hermetic unit tests only.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _load_env_file(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE file, without overriding it.

    Args:
        path: Location of the .env file; silently ignored when absent.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ENV_FILE)
