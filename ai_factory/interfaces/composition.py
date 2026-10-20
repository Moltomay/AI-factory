"""Composition root: the only place where the infrastructure adapters are instantiated."""

from ai_factory.application.ports import TicketSource
from ai_factory.application.process_ticket import ProcessTicket
from ai_factory.infrastructure.github import GitHubVersionControl
from ai_factory.infrastructure.openrouter_agent import OpenRouterAgent
from ai_factory.infrastructure.quality import CommandQualityRunner
from ai_factory.infrastructure.trello import TrelloBoard
from ai_factory.interfaces.config import FactoryConfig


def build_ticket_source(config: FactoryConfig) -> TicketSource:
    """Build the tracker adapter for the configured Trello list."""
    return TrelloBoard(config.trello_api_key, config.trello_token, config.trello_list_id)


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
    return ProcessTicket(
        ticket_source=ticket_source,
        code_agent=build_code_agent(config),
        quality_runner=build_quality_runner(config),
        version_control=build_version_control(config),
    )
