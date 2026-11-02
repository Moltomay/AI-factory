# AI-factory

An MVP "AI factory": agents that pick up tickets from a tracker, implement the change,
check code quality and tests, then open a git pull request for human review.

> Status: step 6b done — `run` processes one ticket end to end and moves the card
> to In Review; `reconcile` applies the pull request outcome to the cards waiting
> in review. The full path was validated on the sandbox repository with a real
> card, a `factory/<ticket_id>` branch and a merged pull request. See `specs/`
> for the execution order.

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
`specs/04-cli.md` for the variable names): Trello board
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

The mutation probe is local-only, never in CI. It mutates the package and keeps
only the lines changed from `main`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mutation.txt
.\.venv\Scripts\Activate.ps1
cosmic-ray init cosmic-ray.toml mutation.sqlite
cr-filter-git --config cosmic-ray.toml mutation.sqlite
cosmic-ray exec cosmic-ray.toml mutation.sqlite
cr-report mutation.sqlite
```

`mutation.sqlite` is local state and stays untracked. The test command runs
`python -B` so mutated modules are never read from a stale `__pycache__`.
Install `cosmic-ray` in the same venv as `pytest`: the test command resolves
`python` from that venv.

## Run locally

```powershell
.\.venv\Scripts\python.exe -m ai_factory run
```

`run` processes the next card of the configured Trello list once: it clones the
sandbox repository into the factory workdir, lets the agent implement the ticket,
runs the deterministic checks, opens a pull request, moves the card to **In
Review**, then comments the pull request URL (or reports the failure and leaves
the card in To Do). It never detects a merge.

### Ticket lifecycle

1. **To Do** (`TRELLO_LIST_ID`) — waiting for `run`.
2. **In Review** (`TRELLO_REVIEW_LIST_ID`) — `run` opened a pull request.
3. **Done** (`TRELLO_DONE_LIST_ID`) — `reconcile` saw that pull request merged.

The three list identifiers are required and must be distinct two by two.

`reconcile` scans the In Review cards and applies the pull request outcome:

```powershell
.\.venv\Scripts\python.exe -m ai_factory reconcile
```

- merged pull request: card moved to Done, no comment;
- closed without merge: card moved back to To Do, then a comment naming the branch;
- open pull request: nothing;
- no pull request found: card kept in In Review, the other cards are still
  processed, and the command exits with `1`.

`reconcile` is re-runnable but only scans In Review: a card already moved is not
seen again, so two runs without a state change move nothing and comment nothing.
A pull request reopened after its card left In Review is not detected.

Configuration comes from the environment, completed by the git-ignored `.env` at
the repository root (real environment variables win); see `specs/04-cli.md` for
the variable names. Exit codes: `0` success (including "no ticket waiting" and a
reconcile without a missing pull request), `1` processing failure (failed
pipeline or at least one missing pull request), `2` invalid configuration.

## Security limits

The agent runtime is a guardrail, not an OS sandbox. Every infrastructure
subprocess receives a sanitized environment (no Trello, OpenRouter, GitHub or
factory secrets), the model can only run an allowlisted set of executables, and
`run_command` restricts git to read-only inspection. The factory itself keeps
`git push` and pull-request creation.

`python` and `pytest` stay allowlisted because the agent must be able to run
checks. They can still start arbitrary code, read files and use the network, so
a prompt injection inside `python` is not contained. A container or VM is out of
scope for the MVP; see `specs/06a-agent-runtime-hardening.md`.

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
