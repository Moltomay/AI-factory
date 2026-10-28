# AGENTS.md

Guidelines for any coding agent working in this repository. Read this fully before writing code. If a task conflicts with a rule here, stop and ask rather than improvising.

**Architecture rules for this repo live in `ARCHITECTURE.md` — read it before coding.**

Rules marked *(enforced)* are checked by tooling (ruff, import-linter, pre-commit, CI). Never bypass them: fix the code, not the check.

## 1. Before you write a line of code

- **Restate the task and the acceptance criteria** in your own words before touching files. If either is ambiguous, ask — don't guess.
- **Write a short spec first**: the behavior/contract expected (inputs, outputs, edge cases, acceptance criteria), not the implementation. For a new use case or pipeline step, this spec is the contract it exposes — define it before deciding how it will be implemented. Once I approve it, save it as `specs/<task>.md` and commit it with the code. Keep it scoped to the task at hand (no exhaustive upfront spec), and change an approved spec only with my approval.
- **Always wait for the go to start coding.** Discuss your plan, what you understood, and the acceptance criteria/spec first, THEN wait for the go before starting the actual work.
- **Locate existing patterns first.** Check for an existing module, util, or convention that already does what you need before adding a new one.
- **Plan the smallest change that satisfies the task.** Every changed line must trace back to the request. No speculative abstractions, no "while I'm here" refactors outside scope; if a bigger refactor seems warranted, propose it separately.
- **Never rewrite a file wholesale.** Existing logic (thresholds, rules, tuned values, workarounds) often encodes hard-won fixes. Change only what the task needs and preserve the rest.
- **Prefer boring, explicit code** over clever one-liners or premature optimization. Readability for a human reviewer beats elegance.
- **Use conda or venv to create a virtual environment** where the project's dependencies live (pip libraries etc.).
- **NEVER IMPORT MODULES/PACKAGES INSIDE A FUNCTION** — imports always go at the top of the Python file. *(enforced)*
- **No new dependency without asking.** Pin versions; don't widen a version range to fix an unrelated issue.

## 2. Boundaries and the safety net

- **Never touch**: `.env*`, secrets/credentials folders, `*.pem`, `*.key`.
- **The safety net is human-owned.** Never weaken it to get green. Changing any of these requires my explicit approval: `ruff.toml`, `.importlinter`, `.pre-commit-config.yaml`, `.github/workflows/**`, `ARCHITECTURE.md`, `AGENTS.md`.
- **Tests**: you may add and extend tests, but never delete, skip, xfail, or loosen an existing one to make a run pass.
- **No suppressions** (`# noqa`, `# type: ignore`, `# pragma: no cover`) without a one-line justification and my approval.
- If a check blocks you, fix the code. If you believe the check itself is wrong, stop and tell me.
- **Human checkpoint** (stop and ask): schema/migration changes, prod deploys, repo settings (branch protection, rulesets), deleting data, external API calls with side effects, force-pushes.

## 3. Architecture

Follow `ARCHITECTURE.md`. The dependency direction it defines is checked automatically by import-linter (`.importlinter`). *(enforced)*

## 4. Testing — non-negotiable

- **Write or update tests for every change**, before or alongside the code (tests-first when feasible). Logic without new/updated tests is incomplete.
- **Tests must assert behavior**, not mirror the implementation. A test that would still pass if the code were wrong is worthless.
- **Every acceptance criterion in the spec maps to at least one test.** Reference the criterion in the test name or docstring so the link is traceable.
- **Unit tests**: deterministic, no network, no Spark session, no GPU — should run in seconds.
- **Integration tests** for adapters that touch external systems (mocked external calls where possible; a small marked subset can hit real sandboxed services).
- **Never use real client data** in tests, fixtures, or notebook outputs — synthetic or anonymized data only.
- **Before declaring a task done**, run locally and report the results: `ruff check .`, `ruff format --check .`, `lint-imports`, and the full test suite. Don't just say "tests should pass."
- If something can be tested via API calls, do it before declaring the task done.
- If something can't reasonably be tested (e.g. a notebook exploration), say so explicitly rather than skipping silently.

## 5. CI pipeline

- Every repo uses the shared `ci.yml` GitHub Actions workflow, with four gates: **secrets scan** (gitleaks), **lint** (ruff check + ruff format + import-linter), **unit tests**, **dependency audit** (pip-audit). Don't hand-roll a different CI config — copy/sync the reusable workflow. If a task needs a new check, propose the change to `ci.yml` (upon my validation) rather than adding an ad-hoc script.
- The CI must always PASS. A red check is not a finished task: if a job fails, read the logs, fix it, and re-push. You have access to git; if not, ask me for a PAT (Personal Access Token).
- Install the local hooks once per clone: `pre-commit install` (gitleaks, ruff, no commits on main).

## 6. Security & secrets

- **Never hardcode secrets, tokens, connection strings, or credentials.** Use environment variables / the project's secret manager (Key Vault, Databricks secrets, etc.) — reference them, don't inline values.
- **Before finishing any task, scan your own diff for accidental secrets**: API keys, connection strings, access tokens, private keys, `.env` contents, hardcoded internal hostnames/IPs. Treat any match as a blocker, not a warning.
- Never commit `.env`, credential files, or exported notebook outputs that embed data samples containing PII.
- **Never log secrets or personal/client data.**
- Validate and sanitize all external/untrusted input (API payloads, uploaded files, query params) at the boundary — don't trust it deeper in the stack.
- Flag (don't just fix) any pattern that looks like a broader security smell — e.g. SQL built by string concatenation, overly broad IAM/role scopes, missing auth checks on an endpoint.

## 7. Documentation — always

- Every public function/class gets a docstring: purpose, parameters, return value, and any non-obvious side effects or assumptions.
- Every module gets a short header comment explaining what it's for and where it sits in the architecture.
- Update the relevant `README.md` when you add a new module, endpoint, or pipeline step — don't leave docs stale.
- Comments explain **why**, not what — the code should already say what it does.

## 8. Failure handling

- **Fail loudly and stop.** If you hit something outside the defined scope, an ambiguous spec, a failing test you can't explain, or a permission-boundary conflict — surface it and stop, don't improvise a workaround silently.
- **Never fabricate** file paths, library functions or parameters, commit hashes, or results. Report only output you actually ran; if you don't know, read the file, run the command, or say so.
- Never suppress an exception just to make a test pass; fix the root cause or report why you can't.
- If you had to make an assumption to proceed, state it explicitly in your summary.
- **Never swallow an exception silently.** No bare `except:` and no `except Exception: pass`. Either handle it meaningfully, re-raise it (with added context), or log it with enough detail to debug. *(enforced)*
- **Catch the specific exception type**, not a blanket `Exception`, unless you're at a true top-level boundary (API error handler, pipeline entry point) where you deliberately convert any failure into a controlled response. *(enforced)*
- Don't use exceptions for normal control flow (e.g. catching `KeyError` instead of checking `if key in dict`) — reserve them for actual error conditions.
- Handle real failure modes only. Don't add error handling for scenarios that cannot happen.

## 9. Step-by-step work and summaries

I want to stay up to date with the codebase, so work step by step, one task at a time — never in one big batch of changes. Each step is a thin vertical slice that leaves the code working, tested and CI-green, not a half-built layer. When feasible, build a minimal end-to-end path first, then widen it.

After **each** step, give a short summary:
- **What was there**: the relevant existing code or behavior before you touched it.
- **What you did and why** (map back to the acceptance criteria), and which files changed.
- Tests added/updated, lint/import-linter results, and CI status.
- Any assumption made, any scope you deliberately left out, and any security/secrets check performed.

When the whole task is finished, end with a short recap across the steps.

TODO.md is my backlog. You may append items, but never reorder, delete, or start one without my go, if we complete an item give me a heads up before deleting it from this file. This file must be untracked by git.

## 10. Git

- Never commit or push to the main branch — always create a feature branch. *(enforced locally by pre-commit)*
- Always ask for permission before committing. Once I've given the go to commit for a task, fix-up commits and pushes needed to get CI green on that same feature branch are covered — don't ask again for each iteration. Never push to main.

## 11. Clean code (micro-level)

Most of this is checked by ruff (complexity, magic values, annotations, unused code, blind excepts — see `ruff.toml`). *(enforced)*

- Functions do one thing. If you need "and" to describe what a function does, split it. Soft limit: ~40 lines; if longer, justify why it isn't split.
- Names say what, not how: `filter_active_users`, not `process_data2`. No single-letter variables outside tight loop indices.
- No magic numbers/strings. Pull them into named constants, even if used once — a reviewer (or future agent) shouldn't have to guess what `0.37` means.
- Max nesting depth ~3. Prefer early returns / guard clauses over deep if/else pyramids.
- No duplicated logic. If you copy-paste more than a few lines, extract it — but don't over-abstract for a single use (rule of three: duplicate twice is fine, three times extract).
- No dead code, no commented-out code, no unused imports/variables left behind — delete, don't comment out "just in case."
- Type hints on all function signatures.
- If you wrote 200 lines where 50 would do, rewrite.
