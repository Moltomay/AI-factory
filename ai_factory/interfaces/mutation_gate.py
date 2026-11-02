"""CI gate for the cosmic-ray mutation probe.

Reads the sqlite database written by ``cosmic-ray exec`` and fails when a
mutant survives outside the human-owned allowlist of semantically equivalent
mutants. Incomplete or invalid results also fail, so a broken probe cannot
silently become a green CI job.

Usage:
    python -m ai_factory.interfaces.mutation_gate <database> <allowlist>
"""

import sqlite3
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Imported under a plain name: cosmic-ray's ExceptionReplacer cannot mutate a
# dotted exception name inside an except clause and reports an invalid mutant.
from sqlite3 import Error as SqliteError
from typing import TextIO

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXPECTED_ARGUMENT_COUNT = 2
ALLOWLIST_SECTION = "mutants"
WORKER_NORMAL = "NORMAL"
WORKER_SKIPPED = "SKIPPED"
TEST_KILLED = "KILLED"
TEST_SURVIVED = "SURVIVED"
USAGE = "Usage: python -m ai_factory.interfaces.mutation_gate <database> <allowlist>"
ERROR_TEMPLATE = "Mutation gate error: {reason}"

RESULTS_QUERY = """
SELECT s.module_path, s.operator_name, s.occurrence, s.start_pos_row,
       r.worker_outcome, r.test_outcome
FROM mutation_specs AS s
LEFT JOIN work_results AS r ON r.job_id = s.job_id
ORDER BY s.module_path, s.start_pos_row, s.operator_name, s.occurrence
"""


@dataclass(frozen=True)
class Mutant:
    """Identity of one mutation, matching the allowlist granularity.

    Attributes:
        file: Module path normalized to POSIX separators.
        line: One-based line where the mutation starts.
        operator: cosmic-ray operator name, e.g. ``core/NumberReplacer``.
        occurrence: Index of the operator occurrence in the module.
    """

    file: str
    line: int
    operator: str
    occurrence: int


@dataclass(frozen=True)
class MutantResult:
    """One mutation and the raw outcome recorded by cosmic-ray.

    Attributes:
        mutant: Identity of the mutation.
        worker_outcome: Worker status, or None when the mutant never ran.
        test_outcome: Test verdict, or None when no verdict was produced.
    """

    mutant: Mutant
    worker_outcome: str | None
    test_outcome: str | None


@dataclass(frozen=True)
class GateReport:
    """Classification of every mutation in one probe database.

    Attributes:
        total: Number of mutation rows read.
        killed: Mutants whose test run failed, as expected.
        skipped: Mutants filtered out because their line is unchanged.
        allowlisted: Surviving mutants covered by the allowlist.
        actionable: Surviving mutants that must be killed or allowlisted.
        invalid: Results that are neither a kill, a survival nor a skip.
        pending: Mutations with no result row at all.
    """

    total: int
    killed: int
    skipped: int
    allowlisted: int
    actionable: tuple[Mutant, ...]
    invalid: tuple[MutantResult, ...]
    pending: tuple[Mutant, ...]

    @property
    def passed(self) -> bool:
        """Whether the probe is complete and has no actionable survivor."""
        return not self.actionable and not self.invalid and not self.pending


def load_allowlist(path: Path) -> dict[tuple[str, str, int, int], str]:
    """Read the human-owned allowlist of equivalent mutants.

    Args:
        path: TOML file with a ``[[mutants]]`` array.

    Returns:
        A mapping from (file, operator, occurrence, line) to its justification.

    Raises:
        OSError: When the file cannot be read.
        TypeError: When a value has the wrong type.
        ValueError: When the TOML is invalid, an entry is incomplete, a reason
            is empty, or the same mutant is listed twice.
    """
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = payload.get(ALLOWLIST_SECTION, [])
    if not isinstance(entries, list):
        raise TypeError(f"'{ALLOWLIST_SECTION}' must be an array of tables")
    allowlist: dict[tuple[str, str, int, int], str] = {}
    for entry in entries:
        key = _allowlist_key(entry)
        if key in allowlist:
            raise ValueError(f"duplicate allowlist entry: {key}")
        allowlist[key] = _allowlist_reason(entry)
    return allowlist


def load_results(path: Path) -> list[MutantResult]:
    """Read every mutation and its optional result from the cosmic-ray database.

    Args:
        path: sqlite database written by ``cosmic-ray exec``.

    Returns:
        One result per mutation row, mutations without a result included.

    Raises:
        OSError: When the database file does not exist or cannot be read.
        sqlite3.Error: When the database schema or query is invalid.
    """
    if not path.is_file():
        raise OSError(f"database not found: {path}")
    with sqlite3.connect(path) as connection:
        rows = connection.execute(RESULTS_QUERY).fetchall()
    return [_result_from_row(row) for row in rows]


def evaluate(
    results: Sequence[MutantResult],
    allowlist: dict[tuple[str, str, int, int], str],
) -> GateReport:
    """Classify every mutation against the allowlist.

    Args:
        results: Mutations and raw outcomes read from the database.
        allowlist: Human-approved equivalent mutants.

    Returns:
        The aggregated, deterministic classification used by the gate.
    """
    killed = 0
    skipped = 0
    allowlisted = 0
    actionable: list[Mutant] = []
    invalid: list[MutantResult] = []
    pending: list[Mutant] = []
    for result in results:
        worker_outcome = _normalized(result.worker_outcome)
        test_outcome = _normalized(result.test_outcome)
        if worker_outcome is None:
            pending.append(result.mutant)
        elif worker_outcome == WORKER_SKIPPED:
            skipped += 1
        elif worker_outcome == WORKER_NORMAL and test_outcome == TEST_KILLED:
            killed += 1
        elif worker_outcome == WORKER_NORMAL and test_outcome == TEST_SURVIVED:
            if _mutant_key(result.mutant) in allowlist:
                allowlisted += 1
            else:
                actionable.append(result.mutant)
        else:
            invalid.append(result)
    return GateReport(
        total=len(results),
        killed=killed,
        skipped=skipped,
        allowlisted=allowlisted,
        actionable=tuple(actionable),
        invalid=tuple(invalid),
        pending=tuple(pending),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the gate and return a process exit code.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        0 when every mutant is killed, skipped or allowlisted, 1 otherwise.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != EXPECTED_ARGUMENT_COUNT:
        _write_line(sys.stderr, USAGE)
        return EXIT_FAILURE
    try:
        allowlist = load_allowlist(Path(arguments[1]))
        results = load_results(Path(arguments[0]))
    except (OSError, TypeError, ValueError, SqliteError) as error:
        _write_line(sys.stderr, ERROR_TEMPLATE.format(reason=error))
        return EXIT_FAILURE
    report = evaluate(results, allowlist)
    _write_report(sys.stdout, report)
    return EXIT_SUCCESS if report.passed else EXIT_FAILURE


def _allowlist_key(entry: object) -> tuple[str, str, int, int]:
    """Validate one allowlist entry and return its stable identity."""
    if not isinstance(entry, dict):
        raise TypeError("each allowlist entry must be a table")
    missing = {"file", "line", "operator", "occurrence"} - entry.keys()
    if missing:
        raise ValueError(f"allowlist entry is missing {sorted(missing)}")
    file_name = entry["file"]
    operator = entry["operator"]
    line = entry["line"]
    occurrence = entry["occurrence"]
    if not isinstance(file_name, str) or not isinstance(operator, str):
        raise TypeError("allowlist 'file' and 'operator' must be strings")
    if not isinstance(line, int) or not isinstance(occurrence, int):
        raise TypeError("allowlist 'line' and 'occurrence' must be integers")
    return (_normalize_path(file_name), operator, occurrence, line)


def _allowlist_reason(entry: object) -> str:
    """Return the non-empty justification attached to one entry."""
    if not isinstance(entry, dict):
        raise TypeError("each allowlist entry must be a table")
    reason = entry.get("reason")
    if not isinstance(reason, str):
        raise TypeError("each allowlist entry needs a string 'reason'")
    if not reason.strip():
        raise ValueError("each allowlist entry needs a non-empty 'reason'")
    return reason


def _normalize_path(path: str) -> str:
    """Normalize a module path so Windows and Linux probes compare equal."""
    return path.replace("\\", "/").removeprefix("./")


def _normalized(outcome: str | None) -> str | None:
    """Uppercase a cosmic-ray outcome; sqlite stores the enum names."""
    return outcome.upper() if outcome else None


def _mutant_key(mutant: Mutant) -> tuple[str, str, int, int]:
    """Build the allowlist key of a mutation."""
    return (mutant.file, mutant.operator, mutant.occurrence, mutant.line)


def _result_from_row(row: tuple[object, ...]) -> MutantResult:
    """Convert one sqlite row to a typed result."""
    mutant = Mutant(
        file=_normalize_path(str(row[0])),
        operator=str(row[1]),
        occurrence=int(row[2]),
        line=int(row[3]),
    )
    worker_outcome = None if row[4] is None else str(row[4])
    test_outcome = None if row[5] is None else str(row[5])
    return MutantResult(
        mutant=mutant,
        worker_outcome=worker_outcome,
        test_outcome=test_outcome,
    )


def _write_report(stream: TextIO, report: GateReport) -> None:
    """Write the summary and every violation to the given stream."""
    _write_line(
        stream,
        (
            f"Mutation gate: {report.total} mutants, {report.killed} killed, "
            f"{report.allowlisted} allowlisted, {report.skipped} skipped, "
            f"{len(report.actionable)} actionable, {len(report.invalid)} invalid, "
            f"{len(report.pending)} pending."
        ),
    )
    for mutant in report.actionable:
        _write_line(
            stream,
            (
                f"ACTIONABLE SURVIVOR {mutant.file}:{mutant.line} "
                f"{mutant.operator} occurrence={mutant.occurrence}"
            ),
        )
    for result in report.invalid:
        _write_line(
            stream,
            (
                f"INVALID RESULT {result.mutant.file}:{result.mutant.line} "
                f"{result.mutant.operator} occurrence={result.mutant.occurrence}: "
                f"worker={result.worker_outcome}, test={result.test_outcome}"
            ),
        )
    for mutant in report.pending:
        _write_line(
            stream,
            (
                f"PENDING {mutant.file}:{mutant.line} "
                f"{mutant.operator} occurrence={mutant.occurrence}"
            ),
        )


def _write_line(stream: TextIO, message: str) -> None:
    """Write one message line to the given stream."""
    stream.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
