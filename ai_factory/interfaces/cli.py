"""Command-line entry point: process the next waiting ticket once."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from ai_factory.application.ports import TicketSource
from ai_factory.application.process_ticket import (
    FAILED_MESSAGE_TEMPLATE,
    PULL_REQUEST_OPENED_MESSAGE_TEMPLATE,
    ProcessTicket,
)
from ai_factory.domain.errors import ExternalServiceError
from ai_factory.interfaces.composition import build_process_ticket, build_ticket_source
from ai_factory.interfaces.config import ConfigurationError, load_config
from ai_factory.interfaces.env import load_env_file

ENV_FILE_NAME = ".env"
NO_TICKET_MESSAGE = "No ticket is waiting in the configured list."
CONFIGURATION_ERROR_TEMPLATE = "Configuration error: {reason}"
PROCESSING_ERROR_TEMPLATE = "Processing error: {reason}"
EXIT_SUCCESS = 0
EXIT_PROCESSING_FAILURE = 1
EXIT_CONFIGURATION_ERROR = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line, run the pipeline and return the process exit code.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:].

    Returns:
        Exit code: 0 on success, 1 on processing failure, 2 on invalid configuration.
    """
    _build_parser().parse_args(argv)
    load_env_file(Path.cwd() / ENV_FILE_NAME)
    try:
        config = load_config(os.environ)
        ticket_source = build_ticket_source(config)
        process = build_process_ticket(config, ticket_source)
        return _process_next_ticket(ticket_source, process)
    except ConfigurationError as error:
        _write_line(sys.stderr, CONFIGURATION_ERROR_TEMPLATE.format(reason=error))
        return EXIT_CONFIGURATION_ERROR
    except ExternalServiceError as error:
        _write_line(sys.stderr, PROCESSING_ERROR_TEMPLATE.format(reason=error))
        return EXIT_PROCESSING_FAILURE


def _process_next_ticket(ticket_source: TicketSource, process: ProcessTicket) -> int:
    """Process one ticket when one is waiting, and report the outcome.

    Args:
        ticket_source: Tracker holding the waiting ticket.
        process: Use case driving the pipeline.

    Returns:
        0 when nothing waited or the pull request was opened, 1 otherwise.
    """
    ticket = ticket_source.fetch_next_ticket()
    if ticket is None:
        _write_line(sys.stdout, NO_TICKET_MESSAGE)
        return EXIT_SUCCESS
    result = process.execute(ticket)
    if result.pull_request_url is None:
        _write_line(sys.stdout, FAILED_MESSAGE_TEMPLATE.format(reason=result.run.failure_reason))
        return EXIT_PROCESSING_FAILURE
    _write_line(
        sys.stdout, PULL_REQUEST_OPENED_MESSAGE_TEMPLATE.format(url=result.pull_request_url)
    )
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai_factory", description="Automated ticket factory.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Process the next waiting ticket once.")
    return parser


def _write_line(stream: TextIO, message: str) -> None:
    """Write one message line to the given stream."""
    stream.write(f"{message}\n")
