"""Entry point for `python -m ai_factory`."""

import sys

from ai_factory.interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
