# AI-factory

An MVP "AI factory": agents that pick up tickets from a tracker, implement the change,
check code quality and tests, then open a git pull request for human review.

> Status: step 3 done — Trello, GitHub and OpenRouter adapters
> (`ai_factory/infrastructure/`), behind the ports defined in step 2. Unit tests
> use fakes only; opt-in integration tests hit the real services. The CLI and the
> end-to-end run are being built step by step; see `specs/` (numbered in
> execution order).

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
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements.txt
.\.venv\Scripts\pre-commit.exe install
```

Secrets come from a git-ignored `.env` at the repository root (see
`specs/03-infrastructure-adapters.md` for the variable names): Trello board
credentials, an OpenRouter API key and model, a GitHub fine-grained PAT
(contents + pull requests read/write) and the sandbox repository. They are never
committed; tests load them through `tests/conftest.py`.

## Checks

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\lint-imports.exe
.\.venv\Scripts\pytest.exe tests/unit -v
```

The same gates run in CI (`.github/workflows/ci.yml`): secrets scan, lint,
unit tests, dependency audit.

## Run locally

```powershell
.\.venv\Scripts\python.exe -m ai_factory run
```

`run` processes the next card of the configured Trello list once: it clones the
sandbox repository into the factory workdir, lets the agent implement the ticket,
runs the deterministic checks, then opens a pull request (or reports the failure
as a Trello comment). Configuration comes from the environment, completed by the
git-ignored `.env` at the repository root (real environment variables win); see
`specs/04-cli.md` for the variable names. Exit codes: `0` success (including
"no ticket waiting"), `1` processing failure, `2` invalid configuration.

## Integration tests (real services, opt-in)

Marked `integration` and skipped when the `.env` variables are missing, so they
never run in CI:

```powershell
.\.venv\Scripts\pytest.exe tests/integration -m integration -v
```

- `test_trello_real.py` — reads the first card of the configured list and
  records a comment.
- `test_github_real.py` — creates a throwaway branch and pull request in the
  sandbox repository (the branch is left for inspection).
- `test_openrouter_real.py` — one real chat completion with the configured model
  (free models can be rate-limited upstream; pick another one if needed).
