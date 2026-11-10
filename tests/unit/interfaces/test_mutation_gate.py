"""Behavior tests for the mutation gate, using a synthetic cosmic-ray database."""

import runpy
import sqlite3
import sys
from pathlib import Path

import pytest

from ai_factory.interfaces import mutation_gate

DATABASE_NAME = "mutation.sqlite"
ALLOWLIST_NAME = "mutation-allowlist.toml"
MODULE_PATH = "ai_factory/infrastructure/github.py"
OPERATOR = "core/NumberReplacer"


def _create_database(
    path: Path,
    rows: list[tuple[str, str, int, int, str | None, str | None]],
) -> None:
    """Write the three cosmic-ray tables needed by the gate."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE work_items (job_id TEXT PRIMARY KEY);
        CREATE TABLE mutation_specs (
            job_id TEXT, module_path TEXT, operator_name TEXT,
            occurrence INTEGER, start_pos_row INTEGER
        );
        CREATE TABLE work_results (
            job_id TEXT, worker_outcome TEXT, test_outcome TEXT
        );
        """
    )
    for index, (module_path, operator, occurrence, line, worker, test) in enumerate(rows):
        job_id = f"job-{index}"
        connection.execute("INSERT INTO work_items VALUES (?)", (job_id,))
        connection.execute(
            "INSERT INTO mutation_specs VALUES (?, ?, ?, ?, ?)",
            (job_id, module_path, operator, occurrence, line),
        )
        if worker is not None:
            connection.execute(
                "INSERT INTO work_results VALUES (?, ?, ?)",
                (job_id, worker, test),
            )
    connection.commit()
    connection.close()


def _entry(
    file: str = MODULE_PATH,
    line: int = 14,
    operator: str = OPERATOR,
    occurrence: int = 0,
) -> str:
    """Build one TOML allowlist entry."""
    return (
        "[[mutants]]\n"
        f'file = "{file}"\n'
        f"line = {line}\n"
        f'operator = "{operator}"\n'
        f"occurrence = {occurrence}\n"
        'reason = "No acceptance criterion observes this value."\n'
    )


def _write_allowlist(path: Path, entries: list[str]) -> None:
    """Write the allowlist entries, one after the other."""
    path.write_text("\n".join(entries), encoding="utf-8")


def test_gate_fails_on_an_actionable_survivor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A surviving mutant outside the allowlist fails and names its location."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "SURVIVED")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert f"ACTIONABLE SURVIVOR {MODULE_PATH}:14 {OPERATOR} occurrence=0" in captured.out
    assert "1 actionable" in captured.out


def test_gate_passes_on_an_allowlisted_survivor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An allowlisted survivor is counted and does not fail the gate."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "SURVIVED")])
    _write_allowlist(allowlist, [_entry()])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 0
    assert "1 allowlisted, 0 skipped, 0 actionable" in capsys.readouterr().out


def test_gate_passes_on_killed_mutants(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Killed mutants pass without needing an allowlist entry."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "KILLED")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 0
    assert "1 killed" in capsys.readouterr().out


def test_gate_ignores_mutants_filtered_out_of_the_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A skipped mutant is a filter decision, not a survivor."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "SKIPPED", None)])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 0
    assert "1 skipped" in capsys.readouterr().out


def test_gate_fails_on_an_incompetent_mutant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An incompetent mutant means the baseline is broken and fails the gate."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "INCOMPETENT")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert "INVALID RESULT" in capsys.readouterr().out


def test_gate_fails_on_a_missing_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A mutation that never ran cannot count as a kill."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, None, None)])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert "PENDING" in capsys.readouterr().out


def test_gate_normalizes_windows_paths_for_the_allowlist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Windows database path matches a POSIX allowlist path."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(
        database, [("ai_factory\\infrastructure\\github.py", OPERATOR, 0, 14, "NORMAL", "SURVIVED")]
    )
    _write_allowlist(allowlist, [_entry()])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 0
    assert "1 allowlisted" in capsys.readouterr().out


def test_gate_rejects_a_duplicate_allowlist_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same mutant cannot be allowlisted twice."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "SURVIVED")])
    _write_allowlist(allowlist, [_entry(), _entry()])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert "duplicate allowlist entry" in capsys.readouterr().err


def test_gate_requires_a_reason_for_every_allowlist_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An allowlist entry without a justification is rejected."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "SURVIVED")])
    allowlist.write_text(
        "[[mutants]]\n"
        f'file = "{MODULE_PATH}"\n'
        "line = 14\n"
        f'operator = "{OPERATOR}"\n'
        "occurrence = 0\n"
        'reason = "   "\n',
        encoding="utf-8",
    )

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert "non-empty 'reason'" in capsys.readouterr().err


def test_gate_reports_a_missing_database_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing database is a controlled gate failure."""
    allowlist = tmp_path / ALLOWLIST_NAME
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(tmp_path / DATABASE_NAME), str(allowlist)])

    assert exit_code == 1
    assert "database not found" in capsys.readouterr().err


def test_gate_reports_a_corrupt_database_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file that is not a sqlite database is a controlled gate failure."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    database.write_text("not a sqlite database", encoding="utf-8")
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert "Mutation gate error:" in capsys.readouterr().err


@pytest.mark.parametrize("worker_outcome", ["SURVIVED", "NO_TEST", "EXCEPTION"])
def test_gate_rejects_an_unknown_worker_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], worker_outcome: str
) -> None:
    """A worker verdict outside the cosmic-ray vocabulary is invalid, not skipped."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, worker_outcome, "KILLED")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    captured = capsys.readouterr().out
    assert "INVALID RESULT" in captured
    assert "0 killed" in captured
    assert "0 skipped" in captured
    assert "ACTIONABLE SURVIVOR" not in captured


@pytest.mark.parametrize("worker_outcome", ["NO_TEST", "EXCEPTION"])
def test_gate_rejects_an_unknown_worker_outcome_with_a_survivor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], worker_outcome: str
) -> None:
    """An unknown worker verdict stays invalid even when the test verdict says survived."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, worker_outcome, "SURVIVED")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    captured = capsys.readouterr().out
    assert "INVALID RESULT" in captured
    assert "ACTIONABLE SURVIVOR" not in captured


def test_gate_rejects_an_unknown_test_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A test verdict outside the cosmic-ray vocabulary is invalid, not a survivor."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "UNKNOWN")])
    _write_allowlist(allowlist, [])

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    captured = capsys.readouterr().out
    assert "INVALID RESULT" in captured
    assert "ACTIONABLE SURVIVOR" not in captured


def test_gate_uses_sys_argv_when_no_arguments_are_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI reads sys.argv when main is called without an explicit list."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "KILLED")])
    _write_allowlist(allowlist, [])
    monkeypatch.setattr(sys, "argv", ["mutation_gate", str(database), str(allowlist)])

    exit_code = mutation_gate.main()

    assert exit_code == 0
    assert "1 killed" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [[], ["only-one"], ["a", "b", "c"]])
def test_gate_rejects_the_wrong_number_of_arguments(
    capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    """Missing or extra arguments print the usage and fail before reading anything."""
    exit_code = mutation_gate.main(arguments)

    assert exit_code == 1
    assert mutation_gate.USAGE in capsys.readouterr().err


@pytest.mark.parametrize(
    ("entry", "expected_message"),
    [
        (
            "[[mutants]]\n"
            "file = 14\n"
            "line = 14\n"
            f'operator = "{OPERATOR}"\n'
            "occurrence = 0\n"
            'reason = "Equivalent."\n',
            "must be strings",
        ),
        (
            "[[mutants]]\n"
            f'file = "{MODULE_PATH}"\n'
            'line = "14"\n'
            f'operator = "{OPERATOR}"\n'
            "occurrence = 0\n"
            'reason = "Equivalent."\n',
            "must be integers",
        ),
    ],
)
def test_gate_rejects_allowlist_entries_with_wrong_types(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    expected_message: str,
) -> None:
    """An allowlist entry with a wrong field type is rejected, not silently accepted."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "KILLED")])
    allowlist.write_text(entry, encoding="utf-8")

    exit_code = mutation_gate.main([str(database), str(allowlist)])

    assert exit_code == 1
    assert expected_message in capsys.readouterr().err


def test_gate_runs_as_a_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Executing the module as __main__ runs the gate and reports the probe result."""
    database = tmp_path / DATABASE_NAME
    allowlist = tmp_path / ALLOWLIST_NAME
    _create_database(database, [(MODULE_PATH, OPERATOR, 0, 14, "NORMAL", "KILLED")])
    _write_allowlist(allowlist, [])
    monkeypatch.setattr(sys, "argv", ["mutation_gate", str(database), str(allowlist)])
    module_path = Path(mutation_gate.__file__).resolve()

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(module_path), run_name="__main__")

    assert exc_info.value.code == 0
    assert "1 killed" in capsys.readouterr().out
