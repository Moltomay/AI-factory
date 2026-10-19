# AI-factory

An MVP "AI factory": agents that pick up tickets from a tracker, implement the change,
check code quality and tests, then open a git pull request for human review.

> Status: step 2 done — domain pipeline model (`ai_factory/domain/`) and the
> `ProcessTicket` use case with its ports (`ai_factory/application/`), both
> covered by unit tests with in-memory fakes. Adapters and CLI are being built
> step by step; see `specs/` (numbered in execution order).

## Architecture

Clean Architecture with four layers; dependencies point inward only:

```
interfaces -> infrastructure -> application -> domain
```

- `ai_factory/domain/` — business rules and entities, pure Python.
- `ai_factory/application/` — use cases and ports (abstract interfaces).
- `ai_factory/infrastructure/` — adapters to the outside world (tracker, LLM, git/GitHub).
- `ai_factory/interfaces/` — entry points (CLI) and composition root.

The working rules live in `AGENTS.md` and `ARCHITECTURE.md`; the layer dependency
direction is enforced by import-linter (`.importlinter`).

## Development setup

Requires Python 3.11 (same as CI).

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\pre-commit.exe install
```

## Checks

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\lint-imports.exe
.\.venv\Scripts\pytest.exe tests/unit -v
```

The same gates run in CI (`.github/workflows/ci.yml`): secrets scan, lint,
unit tests, dependency audit.
