"""Behavior tests for the CLI, with the composition root replaced by fakes (no network)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_factory.application.reconcile_tickets import ReconcileResult
from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.ticket import Ticket
from ai_factory.interfaces import cli as cli_module
from ai_factory.interfaces.cli import (
    NO_TICKET_MESSAGE,
    main,
)
from ai_factory.interfaces.config import ConfigurationError

SENTINEL_VALUE = "sentinel-should-not-be-printed"
PULL_REQUEST_URL = "https://github.com/owner/sandbox/pull/1"
FAILURE_REASON = "Automated processing failed: quality checks failed twice."
RECONCILE_SUMMARY = (
    "Reconcile: 0 merged, 0 returned to To Do, 0 still open, 1 without a pull request, "
    "0 with a failed branch cleanup."
)


class _FakeTicketSource:
    def __init__(self, ticket: Ticket | None) -> None:
        self._ticket = ticket

    def fetch_next_ticket(self) -> Ticket | None:
        return self._ticket

    def report_result(self, ticket: Ticket, message: str) -> None:
        pass


class _FakeProcess:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.processed: list[str] = []

    def execute(self, ticket: Ticket) -> object:
        if self._error is not None:
            raise self._error
        self.processed.append(ticket.ticket_id)
        return self._result


class _FakeReconcile:
    def __init__(self, result: ReconcileResult) -> None:
        self._result = result
        self.calls = 0

    def execute(self) -> ReconcileResult:
        self.calls += 1
        return self._result


def _unexpected_reconcile(config: object, ticket_source: object) -> object:
    raise AssertionError("run must not build the reconcile use case")


def _unexpected_process(config: object, ticket_source: object) -> object:
    raise AssertionError("reconcile must not build the pipeline")


def _make_ticket() -> Ticket:
    return Ticket(ticket_id="42", title="Add hello.txt", description="Create the file.")


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    ticket: Ticket | None,
    result: object = None,
    process_error: Exception | None = None,
) -> tuple[_FakeProcess, list[str]]:
    process = _FakeProcess(result=result, error=process_error)
    loaded_env_files: list[str] = []
    config = SimpleNamespace(github_token=SENTINEL_VALUE)

    monkeypatch.setattr(
        cli_module, "load_env_file", lambda path: loaded_env_files.append(str(path))
    )
    monkeypatch.setattr(cli_module, "load_config", lambda environ: config)
    monkeypatch.setattr(cli_module, "build_ticket_source", lambda config: _FakeTicketSource(ticket))
    monkeypatch.setattr(cli_module, "build_process_ticket", lambda config, source: process)
    monkeypatch.setattr(cli_module, "build_reconcile_tickets", _unexpected_reconcile)
    return process, loaded_env_files


def _install_reconcile_fakes(
    monkeypatch: pytest.MonkeyPatch, result: ReconcileResult
) -> _FakeReconcile:
    reconcile = _FakeReconcile(result)
    config = SimpleNamespace(github_token=SENTINEL_VALUE)

    monkeypatch.setattr(cli_module, "load_env_file", lambda path: None)
    monkeypatch.setattr(cli_module, "load_config", lambda environ: config)
    monkeypatch.setattr(cli_module, "build_ticket_source", lambda config: _FakeTicketSource(None))
    monkeypatch.setattr(cli_module, "build_reconcile_tickets", lambda config, source: reconcile)
    monkeypatch.setattr(cli_module, "build_process_ticket", _unexpected_process)
    return reconcile


def _success_result() -> SimpleNamespace:
    return SimpleNamespace(
        pull_request_url=PULL_REQUEST_URL, run=SimpleNamespace(failure_reason=None)
    )


def _failure_result() -> SimpleNamespace:
    return SimpleNamespace(
        pull_request_url=None, run=SimpleNamespace(failure_reason=FAILURE_REASON)
    )


def test_spec04_ac3_no_waiting_ticket_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC3: an empty list reports it and exits successfully without processing."""
    process, loaded_env_files = _install_fakes(monkeypatch, ticket=None)

    exit_code = main(["run"])

    assert exit_code == 0
    assert NO_TICKET_MESSAGE in capsys.readouterr().out
    assert process.processed == []
    assert Path(loaded_env_files[0]).name == cli_module.ENV_FILE_NAME


def test_spec04_ac4_success_prints_the_pull_request_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC4: a successful run prints the pull request URL and exits zero."""
    process, _ = _install_fakes(monkeypatch, ticket=_make_ticket(), result=_success_result())

    exit_code = main(["run"])

    assert exit_code == 0
    assert PULL_REQUEST_URL in capsys.readouterr().out
    assert process.processed == ["42"]


def test_spec04_ac5_failed_run_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC5: a failed pipeline prints the reason and exits with 1."""
    _install_fakes(monkeypatch, ticket=_make_ticket(), result=_failure_result())

    exit_code = main(["run"])

    assert exit_code == 1
    assert FAILURE_REASON in capsys.readouterr().out


def test_spec04_ac5_configuration_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC5: an invalid configuration is reported on stderr and exits with 2."""

    def failing_load_config(environ: object) -> object:
        raise ConfigurationError("Missing configuration variables: GITHUB_TOKEN")

    _install_fakes(monkeypatch, ticket=_make_ticket())
    monkeypatch.setattr(cli_module, "load_config", failing_load_config)

    exit_code = main(["run"])

    assert exit_code == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_spec04_ac5_ac7_processing_error_exits_one_without_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC5/AC7: a service failure exits with 1 and never prints configuration values."""
    _install_fakes(
        monkeypatch,
        ticket=_make_ticket(),
        process_error=ExternalServiceError("HTTP 403 for POST /pulls"),
    )

    exit_code = main(["run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "HTTP 403" in captured.err
    assert SENTINEL_VALUE not in captured.out
    assert SENTINEL_VALUE not in captured.err


def test_spec06b_ac11_run_does_not_build_the_reconcile_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11: `run` never builds the reconcile use case."""
    process, _ = _install_fakes(monkeypatch, ticket=None)

    exit_code = main(["run"])

    assert exit_code == 0
    assert process.processed == []


def test_spec06b_ac11_reconcile_does_not_build_the_pipeline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC11: `reconcile` runs the reconcile use case only."""
    reconcile = _install_reconcile_fakes(monkeypatch, ReconcileResult((), (), (), ()))

    exit_code = main(["reconcile"])

    assert exit_code == 0
    assert reconcile.calls == 1
    assert (
        "Reconcile: 0 merged, 0 returned to To Do, 0 still open, 0 without a pull request, "
        "0 with a failed branch cleanup." in capsys.readouterr().out
    )


def test_spec06b_ac9_missing_pull_request_exits_one_and_reports_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC9: a card without a pull request makes the whole reconcile exit with 1."""
    missing = _make_ticket()
    _install_reconcile_fakes(monkeypatch, ReconcileResult((), (), (), (missing,)))

    exit_code = main(["reconcile"])

    assert exit_code == 1
    assert RECONCILE_SUMMARY in capsys.readouterr().out


def test_spec06b_ac13_failed_cleanup_exits_one_and_reports_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC13: a card stuck by a failed branch cleanup makes reconcile exit with 1."""
    stuck = _make_ticket()
    _install_reconcile_fakes(monkeypatch, ReconcileResult((), (), (), (), (stuck,)))

    exit_code = main(["reconcile"])

    assert exit_code == 1
    assert "0 without a pull request, 1 with a failed branch cleanup." in (capsys.readouterr().out)


def test_spec06b_ac11_reconcile_configuration_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC11: an invalid configuration on `reconcile` is reported and exits with 2."""

    def failing_load_config(environ: object) -> object:
        raise ConfigurationError("Missing configuration variables: TRELLO_DONE_LIST_ID")

    _install_reconcile_fakes(monkeypatch, ReconcileResult((), (), (), ()))
    monkeypatch.setattr(cli_module, "load_config", failing_load_config)

    exit_code = main(["reconcile"])

    assert exit_code == 2
    assert "TRELLO_DONE_LIST_ID" in capsys.readouterr().err


def test_spec06b_ac11_missing_subcommand_is_refused() -> None:
    """AC11: a command is required; no argument does not silently run a command."""
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2


def test_spec06b_ac11_reconcile_is_dispatched_by_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11: the command is compared by value, not by string identity."""
    reconcile = _install_reconcile_fakes(monkeypatch, ReconcileResult((), (), (), ()))
    command = "".join(("recon", "cile"))

    exit_code = main([command])

    assert exit_code == 0
    assert reconcile.calls == 1
