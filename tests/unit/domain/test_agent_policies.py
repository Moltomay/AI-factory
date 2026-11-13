"""Behavior tests for the factory-owned agent policies (spec 07, AC5-AC7)."""

from dataclasses import FrozenInstanceError

import pytest

from ai_factory.domain.agent_policies import (
    AGENT_POLICIES,
    CODE_REVIEW_POLICY,
    DEVELOPER_POLICY,
    OUTPUT_CONTRACT_SECTION,
    SPEC_WRITER_POLICY,
    AgentPolicy,
    policy_for,
)
from ai_factory.domain.pipeline import AgentRole

POLICY_SECTION_ORDER = [
    "ROLE",
    "MISSION",
    "OWNS",
    "DOES NOT OWN",
    "RULES",
    OUTPUT_CONTRACT_SECTION,
]


def test_spec07_ac5_policy_is_an_immutable_value_object() -> None:
    """AC5: the policy exposes its contract and cannot be mutated after creation."""
    policy = DEVELOPER_POLICY

    assert isinstance(policy, AgentPolicy)
    assert policy.role is AgentRole.DEVELOPER
    assert policy.title
    assert policy.mission
    assert policy.owns
    assert policy.does_not_own
    assert policy.rules
    assert policy.output_contract

    with pytest.raises(FrozenInstanceError):
        policy.__setattr__("title", "hijacked")


def test_spec07_ac5_render_is_deterministic_and_ordered() -> None:
    """AC5: rendering twice yields the same text, with the six sections in order."""
    first_render = CODE_REVIEW_POLICY.render()
    second_render = CODE_REVIEW_POLICY.render()

    assert first_render == second_render
    sections = first_render.split("\n\n")
    assert [section.splitlines()[0].split(":")[0] for section in sections] == POLICY_SECTION_ORDER


def test_spec07_ac5_policy_for_every_role() -> None:
    """AC5: every current agent role has exactly one factory-owned policy."""
    assert set(AGENT_POLICIES) == set(AgentRole)
    assert policy_for(AgentRole.SPEC_WRITER) is SPEC_WRITER_POLICY
    assert policy_for(AgentRole.DEVELOPER) is DEVELOPER_POLICY
    assert policy_for(AgentRole.CODE_REVIEWER) is CODE_REVIEW_POLICY


def test_spec07_ac6_developer_policy_contains_the_validated_rules() -> None:
    """AC6: the Coding policy carries the agreed working rules."""
    prompt = DEVELOPER_POLICY.render().lower()

    expected_rules = [
        "smallest change",
        "preserve existing logic",
        "tests for every change",
        "architecture",
        "imports at the top",
        "type hints",
        "docstrings",
        "magic",
        "nesting deeper than three levels",
        "dead code",
        "dependency",
        "secrets",
        "personal data",
        "catch specific exceptions",
        "noqa",
        "human-owned",
        "ruff check",
        "pytest",
        "handoff summary",
    ]
    for rule in expected_rules:
        assert rule in prompt, rule


def test_spec07_ac6_developer_policy_owns_neither_review_nor_acceptance_criteria() -> None:
    """AC6: reviewing its own work and defining the ACs stay out of the Coding mandate."""
    prompt = DEVELOPER_POLICY.render().lower()

    assert "does not own" in prompt
    assert "reviewing its own work" in prompt
    assert "redefining the acceptance criteria" in prompt


def test_spec07_ac7_review_policy_checks_conformance_first() -> None:
    """AC7: spec and AC conformance is the first review responsibility."""
    first_owned = CODE_REVIEW_POLICY.owns[0].lower()

    assert "conformance" in first_owned
    assert "acceptance criteria" in first_owned
    assert "first check conformance" in CODE_REVIEW_POLICY.render().lower()


def test_spec07_ac7_review_policy_order_matches_the_checklist() -> None:
    """AC7: the review checklist keeps its agreed order."""
    owners = [owner.lower() for owner in CODE_REVIEW_POLICY.owns]
    checklist_keywords = [
        "conformance",
        "test relevance",
        "security",
        "design and contracts",
        "error handling",
        "scope",
        "operability",
        "clean code",
    ]

    for owner, keyword in zip(owners, checklist_keywords, strict=True):
        assert keyword in owner, (keyword, owner)


def test_spec07_ac7_review_policy_covers_quality_security() -> None:
    """AC7: the former Quality & Security checklist lives inside Code Review."""
    prompt = CODE_REVIEW_POLICY.render().lower()

    assert "quality and security" in prompt
    assert "secrets in the diff" in prompt
    assert "injection" in prompt
    assert "missing authorization" in prompt
    assert "personal data in logs" in prompt
    assert "lint and formatting" in prompt


def test_spec07_ac7_review_policy_requires_evidence() -> None:
    """AC7: no finding without proof, and no trust in the developer summary."""
    prompt = CODE_REVIEW_POLICY.render().lower()

    assert "evidence" in prompt
    assert "developer's summary" in prompt
    assert "unverified" in prompt
    assert "never invent evidence" in prompt


def test_spec07_ac7_review_policy_is_read_only_and_defers_to_the_gate() -> None:
    """AC7: the reviewer does not edit code, rerun lint or the full suite, or redefine ACs."""
    prompt = CODE_REVIEW_POLICY.render().lower()

    assert "does not own" in prompt
    assert "the deterministic gate is authoritative" in prompt
    assert "do not modify code or tests" in prompt
    assert "do not run lint, formatting or the full test suite" in prompt
    assert "do not redefine acceptance criteria" in prompt


def test_spec07_ac7_review_policy_returns_one_verdict_with_derived_approval() -> None:
    """AC7: a single JSON verdict, with approval derived from the findings."""
    prompt = CODE_REVIEW_POLICY.render().lower()

    assert "one json object" in prompt
    assert '"findings"' in prompt
    assert "approval is derived" in prompt
    assert "never emit or rely on an approved field" in prompt
    assert "minor finding is reported" in prompt


def test_spec06e_ac10_spec_policy_is_factory_owned_and_complete() -> None:
    """AC10: the Spec policy carries the validated rules and the bounds."""
    policy = SPEC_WRITER_POLICY
    prompt = policy.render().lower()

    assert isinstance(policy, AgentPolicy)
    assert policy.role is AgentRole.SPEC_WRITER
    expected_rules = [
        "quote the ticket",
        "never invent",
        "scope",
        "acceptance criteria",
        "unknowns",
        "definition of done",
        "needs_clarification",
        "do not write code",
        "secrets",
        "personal data",
        "one json object",
        "no tools",
        "1 to 20 acceptance criteria",
        "15 scope items",
        "5 questions",
        "condense",
    ]
    for rule in expected_rules:
        assert rule in prompt, rule


def test_spec06e_ac10_spec_policy_owns_neither_code_nor_the_repository() -> None:
    """AC10: the Spec agent does not write code, review, or read the target repository."""
    prompt = SPEC_WRITER_POLICY.render().lower()

    assert "does not own" in prompt
    assert "writing or reviewing code" in prompt
    assert "reading the target repository" in prompt
    assert "agents.md" not in prompt
    assert "architecture.md" not in prompt
    assert "ruff.toml" not in prompt


def test_spec06e_ac10_output_contract_carries_both_schemas() -> None:
    """AC10: the Spec output contract declares the ready and clarification shapes."""
    contract = SPEC_WRITER_POLICY.output_contract

    assert '"status": "ready"' in contract
    assert '"status": "needs_clarification"' in contract
    assert '"acceptance_criteria"' in contract
    assert '"ticket_quote"' in contract
    assert '"questions"' in contract
