"""Behavior tests for the CLI, with the composition root replaced by fakes (no network)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_factory.domain.errors import ExternalServiceError
from ai_factory.domain.ticket import Ticket
from ai_factory.interfaces import cli as cli_module
from ai_factory.interfaces.cli import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_PROCESSING_FAILURE,
    EXIT_SUCCESS,
    NO_TICKET_MESSAGE,
    main,
)
from ai_factory.interfaces.config import ConfigurationError

SENTINEL_VALUE = "sentinel-should-not-be-printed"
PULL_REQUEST_URL = "https://github.com/owner/sandbox/pull/1"
FAILURE_REASON = "Automated processing failed: quality checks failed twice."


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
    return process, loaded_env_files


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

    assert exit_code == EXIT_SUCCESS
    assert NO_TICKET_MESSAGE in capsys.readouterr().out
    assert process.processed == []
    assert Path(loaded_env_files[0]).name == cli_module.ENV_FILE_NAME


def test_spec04_ac4_success_prints_the_pull_request_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC4: a successful run prints the pull request URL and exits zero."""
    process, _ = _install_fakes(monkeypatch, ticket=_make_ticket(), result=_success_result())

    exit_code = main(["run"])

    assert exit_code == EXIT_SUCCESS
    assert PULL_REQUEST_URL in capsys.readouterr().out
    assert process.processed == ["42"]


def test_spec04_ac5_failed_run_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC5: a failed pipeline prints the reason and exits with 1."""
    _install_fakes(monkeypatch, ticket=_make_ticket(), result=_failure_result())

    exit_code = main(["run"])

    assert exit_code == EXIT_PROCESSING_FAILURE
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

    assert exit_code == EXIT_CONFIGURATION_ERROR
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
    assert exit_code == EXIT_PROCESSING_FAILURE
    assert "HTTP 403" in captured.err
    assert SENTINEL_VALUE not in captured.out
    assert SENTINEL_VALUE not in captured.err
