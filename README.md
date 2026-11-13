# AI-factory

An MVP "AI factory": agents that pick up tickets from a tracker, implement the change,
check code quality and tests, then open a git pull request for human review.

> Status: steps 06e and 07 done — the factory drives the Spec, Coding and Code
> Review agents. `run` processes one ticket end to end and moves the card to In
> Review; `reconcile` applies the pull request outcome to the cards waiting in
> review. The full path was validated on the sandbox repository with a real
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

## Agent team

`run` drives a fixed sequence of agents. The team is three agents: Spec, Coding
and Code Review.

| Agent | Stage | Mandate |
|---|---|---|
| Spec | specifying | turns the ticket into the bounded specification both other agents work against: problem, scope in/out, numbered acceptance criteria, unknowns, definition of done; asks for clarification instead of inventing |
| Coding | implementing | writes the change and answers the review findings |
| Code Review | review | final gate: conformance to the spec/ACs first, then tests, security, design/architecture, error handling, scope, operability and clean code |

The Spec stage produces a `Specification` that lives **in memory**
(`PipelineRun.specification`) for the duration of the run. It is never written
into the target clone and never becomes a pull request file. Persistence and
audit of the artifact are deferred to **Spec 10 — Logging & audit trail**.

`validate_spec_outcome` checks the artifact before any branch is created: exact
JSON shape, 1–20 sequential acceptance criteria (`AC1..ACn`), unique statements,
verbatim ticket quotes (whitespace normalized, case preserved), per-item bounds
and a 16,000-character total. An invalid reply gets exactly one corrective retry
in the adapter, then `ExternalServiceError`. A ticket that cannot be specified
without invention returns `needs_clarification`: the run ends in `FAILED`, no
branch is created, no pull request is opened, and the questions are reported on
the card. The same validated specification is passed to every Coding attempt and
to its Code Review, including after a rejection. The pull request body gains an
`## Acceptance criteria` section listing `ACn: statement` (the ticket quotes stay
in memory).

The former Quality & Security checklist is integrated into Code Review, not
removed: one reviewer owns tests vs the acceptance criteria, meaningful
assertions, edge cases, and the security issues the tooling cannot see, along
with the design, failure-mode and operability review.

The agent policies are **factory-owned** (`ai_factory/domain/agent_policies.py`):
static, versioned with the factory, and never read from the target repository.
No repository digest is built. The target repository's `AGENTS.md`,
`ARCHITECTURE.md`, `ruff.toml` and CI files are not read by the agents.

The deterministic gate stays minimal: `ruff check .` then `pytest`, run in the
target clone with the factory venv (`sys.executable -m pytest -q`); `pytest` is
skipped only when the clone has no `tests/` directory. The gate runs before the
Code Review agent and is authoritative. When it fails, the agent is **not**
called: the finding goes straight back to the developer. No other check runs in
the factory gate; `ruff format --check`, `lint-imports`, Bandit and pip-audit run
in CI only.

The Code Review agent returns the shared finding schema: `severity`
(`blocker`/`major`/`minor`), `category`, `location` (`path:line`), `message`,
`evidence`, `status` (`verified`/`unverified`) and an optional `ac`. A finding
without evidence is not accepted. **Approval is derived from the findings**: a
review is approved only when it contains no blocker and no major, so the model
cannot approve a change while reporting a blocker. Findings are sorted by severity
and capped at 20 per review. `minor` findings do not block; they are carried into
the pull request body.

An invalid verdict gets exactly one corrective retry, without tools. A second
failure stops the run and leaves the card in To Do. See
`specs/07-agent-team-simplification.md`; `specs/06d-agent-team.md` records the
superseded four-agent design.

## Prerequisites

### Runtime

- Python 3.11 (same as CI) and `git` on `PATH`.
- Network access to Trello, GitHub and OpenRouter over HTTPS.

### Accounts and access

| Service | What is required |
|---|---|
| Trello | An API key and a user token, plus one board with three lists: **To Do**, **In Review** and **Done**. The token must read cards, move them and add comments. |
| GitHub | A fine-grained personal access token scoped to the **target repository**, with **Contents: read/write** (clone, push `factory/<ticket_id>`) and **Pull requests: read/write** (open and inspect pull requests). Grant **Workflows** only if tickets must change CI files. |
| OpenRouter | An API key and a model identifier that supports **tool calling**. Free models work but are rate-limited; see **Limits** below. |

The target repository is cloned into `FACTORY_WORKDIR` (default
`factory-workdir` under the system temp directory, `%TEMP%` on Windows) and
branched from `origin/main`; it does not need any factory-specific file. The target repository must accept pushes to `factory/*`
branches and pull requests targeting `main`. The agents do not read the target
repository's `AGENTS.md`, `ARCHITECTURE.md`, `ruff.toml` or CI files: their rules
are factory-owned.

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `TRELLO_API_KEY` | yes | Trello API key. |
| `TRELLO_TOKEN` | yes | Trello user token. |
| `TRELLO_LIST_ID` | yes | List holding the tickets to process. |
| `TRELLO_REVIEW_LIST_ID` | yes | List holding the tickets whose pull request is open. |
| `TRELLO_DONE_LIST_ID` | yes | List holding the tickets whose pull request was merged. |
| `OPENROUTER_API_KEY` | yes | OpenRouter API key. |
| `OPENROUTER_MODEL` | yes | OpenRouter model identifier (must support tool calling). |
| `GITHUB_TOKEN` | yes | Token allowed to push and open pull requests on the target repository. |
| `GITHUB_REPOSITORY` | yes | Target repository in `owner/name` form. |
| `FACTORY_WORKDIR` | no | Factory state directory; defaults to `factory-workdir` under the system temp directory. |

The three Trello list identifiers must be distinct. Values come from the
environment or from the git-ignored `.env` at the repository root; real
environment variables win. A missing or blank required variable makes the CLI
exit with `2`.

### Compatibility matrix

| Component | Supported today | Planned |
|---|---|---|
| Ticket tracker | Trello | Jira, Azure DevOps (spec 09) |
| Version control | GitHub | — |
| Agent runtime | OpenRouter (OpenAI-compatible API) | — |
| Trigger | Manual CLI (`run`, `reconcile`) | Polling, then Trello webhook (spec 08) |

### Limits

- One ticket per `run`; there is no queue and no resume after a crash.
- `run` never merges: a human reviews and merges the pull request, then
  `reconcile` moves the card.
- Free OpenRouter models are rate-limited (observed: 20 requests/minute and
  50 requests/day, daily reset at 00:00 UTC); a full run can fail with HTTP 429.
  Use a paid key or a higher limit for unattended runs.
- The agent runtime is a guardrail, not an OS sandbox; see **Security limits**.

## Development setup

Requires Python 3.11 (same as CI).

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements.txt
.\.venv\Scripts\pre-commit.exe install
```

Secrets come from a git-ignored `.env` at the repository root (see
**Prerequisites** for the variable names): Trello board
credentials, an OpenRouter API key and model, a GitHub fine-grained PAT
(contents + pull requests read/write) and the sandbox repository. They are never
committed; tests load them through `tests/conftest.py`.

## Checks

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\lint-imports.exe
.\.venv\Scripts\pytest.exe tests/unit -v --cov=ai_factory --cov-report=term-missing --cov-fail-under=90
```

The same gates run in CI (`.github/workflows/ci.yml`): secrets scan, lint,
unit tests with line coverage, security scan (Bandit, medium+), mutation testing,
dependency audit. The unit test job fails below 90% line coverage
(`--cov-fail-under=90`), measured on the whole package. Coverage answers "what
never runs"; the mutation probe answers "is the changed line actually asserted".

The mutation probe runs locally and in CI. It mutates the package, keeps only
the lines changed from `origin/main`, and fails on any survivor that is not in
`mutation-allowlist.toml`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mutation.txt
.\.venv\Scripts\Activate.ps1
cosmic-ray init cosmic-ray.toml mutation.sqlite
cr-filter-git --config cosmic-ray.toml mutation.sqlite
cosmic-ray exec cosmic-ray.toml mutation.sqlite
.\.venv\Scripts\python.exe -m ai_factory.interfaces.mutation_gate mutation.sqlite mutation-allowlist.toml
cr-report mutation.sqlite
```

`mutation.sqlite` is local state and stays untracked. The test command runs
`python -X utf8 -B` so cosmic-ray stays on UTF-8 and mutated modules are never
read from a stale `__pycache__`. Install `cosmic-ray` in the same venv as
`pytest`: the test command resolves `python` from that venv. Only semantically
equivalent survivors belong in the allowlist, each with a one-line reason; an
actionable survivor must be killed by a test.

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
- closed without merge: remote branch deleted, card moved back to To Do, then a
  comment naming the branch;
- open pull request: nothing;
- no pull request found: card kept in In Review, the other cards are still
  processed, and the command exits with `1`;
- branch deletion failed: card kept in In Review, the other cards are still
  processed, and the command exits with `1`.

`reconcile` is re-runnable but only scans In Review: a card already moved is not
seen again, so two runs without a state change move nothing and comment nothing.
A pull request reopened after its card left In Review is not detected. Deleting
an already absent branch is a success, so a retry after a manual cleanup still
moves the card.

Configuration comes from the environment, completed by the git-ignored `.env` at
the repository root (real environment variables win); see `specs/04-cli.md` for
the variable names. Exit codes: `0` success (including "no ticket waiting" and a
reconcile without a missing pull request or cleanup failure), `1` processing
failure (failed pipeline, at least one missing pull request, or at least one
branch that could not be deleted), `2` invalid configuration.

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
