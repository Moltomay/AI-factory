"""Composition root: the only place where the infrastructure adapters are instantiated."""

from ai_factory.application.ports import TicketSource
from ai_factory.application.process_ticket import ProcessTicket
from ai_factory.application.reconcile_tickets import ReconcileTickets
from ai_factory.infrastructure.github import GitHubVersionControl
from ai_factory.infrastructure.openrouter_agent import OpenRouterAgent
from ai_factory.infrastructure.quality import CommandQualityRunner
from ai_factory.infrastructure.trello import TrelloBoard, TrelloLists
from ai_factory.interfaces.config import FactoryConfig


def build_trello_lists(config: FactoryConfig) -> TrelloLists:
    """Group the three Trello list identifiers driving the ticket lifecycle."""
    return TrelloLists(
        todo=config.trello_list_id,
        in_review=config.trello_review_list_id,
        done=config.trello_done_list_id,
    )


def build_ticket_source(config: FactoryConfig) -> TicketSource:
    """Build the tracker adapter for the configured Trello lists."""
    return TrelloBoard(config.trello_api_key, config.trello_token, build_trello_lists(config))


def build_code_agent(config: FactoryConfig) -> OpenRouterAgent:
    """Build the LLM agent working inside the shared clone."""
    return OpenRouterAgent(
        config.openrouter_api_key, config.openrouter_model, config.clone_directory
    )


def build_quality_runner(config: FactoryConfig) -> CommandQualityRunner:
    """Build the deterministic check runner working inside the shared clone."""
    return CommandQualityRunner(config.clone_directory)


def build_version_control(config: FactoryConfig) -> GitHubVersionControl:
    """Build the git/GitHub adapter working inside the shared clone."""
    return GitHubVersionControl(
        config.github_token, config.github_repository, config.clone_directory
    )


def build_process_ticket(config: FactoryConfig, ticket_source: TicketSource) -> ProcessTicket:
    """Wire every adapter into the process-ticket use case.

    Args:
        config: Validated factory configuration.
        ticket_source: Already-built tracker adapter, shared with the caller.
    """
    agent = build_code_agent(config)
    return ProcessTicket(
        ticket_source=ticket_source,
        spec_agent=agent,
        code_agent=agent,
        quality_runner=build_quality_runner(config),
        version_control=build_version_control(config),
    )


def build_reconcile_tickets(config: FactoryConfig, ticket_source: TicketSource) -> ReconcileTickets:
    """Wire the reconcile use case to the tracker and the GitHub adapter.

    Args:
        config: Validated factory configuration.
        ticket_source: Already-built tracker adapter, shared with the caller.
    """
    return ReconcileTickets(
        ticket_source=ticket_source,
        version_control=build_version_control(config),
    )
