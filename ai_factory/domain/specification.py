"""Specification artifact shared by the Coding and Code Review agents.

The Spec agent turns a ticket into this bounded artifact; a deterministic
validator (added with the spec agent) checks its structure and traceability
before the factory creates a branch. The artifact lives in memory for the
duration of the run (spec 06e); persistence and audit are deferred to spec 10.
"""

from dataclasses import dataclass

from ai_factory.domain.errors import InvalidSpecificationError
from ai_factory.domain.ticket import Ticket

SPEC_STATUS_READY = "ready"
SPEC_STATUS_NEEDS_CLARIFICATION = "needs_clarification"

MIN_ACCEPTANCE_CRITERIA = 1
MAX_ACCEPTANCE_CRITERIA = 20
MAX_SPEC_CHARS = 16_000
MAX_PROBLEM_CHARS = 1_500
MAX_AC_STATEMENT_CHARS = 300
MAX_TICKET_QUOTE_CHARS = 300
MAX_SCOPE_ITEMS = 15
MAX_SCOPE_ITEM_CHARS = 200
MAX_UNKNOWNS = 10
MAX_UNKNOWN_CHARS = 200
MAX_DEFINITION_OF_DONE_ITEMS = 10
MAX_DEFINITION_OF_DONE_CHARS = 200
MAX_CLARIFICATION_QUESTIONS = 5
MAX_QUESTION_CHARS = 300
MAX_CLARIFICATION_CHARS = 2_000

PROBLEM_HEADER = "PROBLEM"
SCOPE_IN_HEADER = "SCOPE IN"
SCOPE_OUT_HEADER = "SCOPE OUT"
ACCEPTANCE_CRITERIA_HEADER = "ACCEPTANCE CRITERIA"
UNKNOWNS_HEADER = "UNKNOWNS"
DEFINITION_OF_DONE_HEADER = "DEFINITION OF DONE"
QUESTIONS_HEADER = "CLARIFICATION QUESTIONS"
CRITERION_LINE_TEMPLATE = "{criterion_id}: {statement}"
CRITERION_QUOTE_TEMPLATE = "  ticket quote: {quote}"

READY_KEYS = frozenset(
    {
        "status",
        "problem",
        "scope_in",
        "scope_out",
        "acceptance_criteria",
        "unknowns",
        "definition_of_done",
    }
)
CLARIFICATION_KEYS = frozenset({"status", "questions"})
ACCEPTANCE_CRITERION_KEYS = frozenset({"id", "statement", "ticket_quote"})


@dataclass(frozen=True)
class AcceptanceCriterion:
    """One testable acceptance criterion, traceable to a ticket sentence.

    Attributes:
        id: Sequential identifier, ``AC1`` to ``ACn``.
        statement: Observable behaviour the change must satisfy.
        ticket_quote: Verbatim sentence of the ticket this criterion comes from.
    """

    id: str
    statement: str
    ticket_quote: str


@dataclass(frozen=True)
class Specification:
    """Bounded contract the Coding and Code Review agents both work against.

    Attributes:
        problem: Ticket problem restated with its own words.
        scope_in: What the change includes.
        scope_out: What the change explicitly excludes.
        acceptance_criteria: Numbered, testable criteria in ticket order.
        unknowns: Assumptions and open points the requester must confirm.
        definition_of_done: Checks expected before the pull request.
    """

    problem: str
    scope_in: tuple[str, ...]
    scope_out: tuple[str, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    unknowns: tuple[str, ...]
    definition_of_done: tuple[str, ...]

    def render(self) -> str:
        """Render the specification as deterministic text for the agents.

        Returns:
            Every field, under fixed section headers, in a stable order.
        """
        sections = [
            f"{PROBLEM_HEADER}:\n{self.problem}",
            _render_list(SCOPE_IN_HEADER, self.scope_in),
            _render_list(SCOPE_OUT_HEADER, self.scope_out),
            _render_criteria(self.acceptance_criteria),
            _render_list(UNKNOWNS_HEADER, self.unknowns),
            _render_list(DEFINITION_OF_DONE_HEADER, self.definition_of_done),
        ]
        return "\n\n".join(sections)


@dataclass(frozen=True)
class SpecOutcome:
    """Result of the Spec stage: either a specification or clarification questions.

    Attributes:
        specification: Validated specification when the ticket is clear.
        questions: Actionable questions when the ticket is ambiguous.
    """

    specification: Specification | None = None
    questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.specification is None) == (not self.questions):
            raise InvalidSpecificationError(
                "a spec outcome carries exactly one of a specification or questions"
            )

    def render(self) -> str:
        """Render the outcome as deterministic text for the agents.

        Returns:
            The specification rendering, or the clarification questions.
        """
        if self.specification is not None:
            return self.specification.render()
        return _render_list(QUESTIONS_HEADER, self.questions)


def _render_list(header: str, items: tuple[str, ...]) -> str:
    """Render one bullet list section, preserving the declared order."""
    return "\n".join([f"{header}:", *(f"- {item}" for item in items)])


def _render_criteria(criteria: tuple[AcceptanceCriterion, ...]) -> str:
    """Render the acceptance criteria with their ticket quotes."""
    lines = [f"{ACCEPTANCE_CRITERIA_HEADER}:"]
    for criterion in criteria:
        lines.append(
            CRITERION_LINE_TEMPLATE.format(criterion_id=criterion.id, statement=criterion.statement)
        )
        lines.append(CRITERION_QUOTE_TEMPLATE.format(quote=criterion.ticket_quote))
    return "\n".join(lines)


def validate_spec_outcome(payload: object, ticket: Ticket) -> SpecOutcome:
    """Validate one Spec agent reply against the contract and the ticket.

    The validator checks structure, bounds and traceability only: whether an
    acceptance criterion is meaningful stays with the policy and the reviewer.

    Args:
        payload: Parsed JSON reply of the Spec agent.
        ticket: Ticket the specification must stay traceable to.

    Returns:
        The validated outcome: a specification or clarification questions.

    Raises:
        InvalidSpecificationError: When the payload is malformed, out of bounds,
            or cites text that is not in the ticket.
    """
    data = _require_object(payload, "specification payload")
    status = data.get("status")
    if status == SPEC_STATUS_READY:
        return _validate_ready(data, ticket)
    if status == SPEC_STATUS_NEEDS_CLARIFICATION:
        return _validate_clarification(data)
    raise InvalidSpecificationError(
        f"status must be one of: {SPEC_STATUS_READY}, {SPEC_STATUS_NEEDS_CLARIFICATION}"
    )


def _validate_ready(data: dict[str, object], ticket: Ticket) -> SpecOutcome:
    """Validate a ready specification and return the bounded artifact."""
    _require_exact_keys(data, READY_KEYS, "ready specification")
    problem = _require_text(data, "problem", MAX_PROBLEM_CHARS)
    scope_in = _require_text_list(data, "scope_in", 1, MAX_SCOPE_ITEMS, MAX_SCOPE_ITEM_CHARS)
    scope_out = _require_text_list(data, "scope_out", 0, MAX_SCOPE_ITEMS, MAX_SCOPE_ITEM_CHARS)
    criteria = _require_criteria(data, ticket)
    unknowns = _require_text_list(data, "unknowns", 0, MAX_UNKNOWNS, MAX_UNKNOWN_CHARS)
    definition_of_done = _require_text_list(
        data,
        "definition_of_done",
        1,
        MAX_DEFINITION_OF_DONE_ITEMS,
        MAX_DEFINITION_OF_DONE_CHARS,
    )
    specification = Specification(
        problem=problem,
        scope_in=scope_in,
        scope_out=scope_out,
        acceptance_criteria=criteria,
        unknowns=unknowns,
        definition_of_done=definition_of_done,
    )
    if len(specification.render()) > MAX_SPEC_CHARS:
        raise InvalidSpecificationError(
            f"rendered specification must be at most {MAX_SPEC_CHARS} characters"
        )
    return SpecOutcome(specification=specification)


def _validate_clarification(data: dict[str, object]) -> SpecOutcome:
    """Validate a clarification payload and return its questions."""
    _require_exact_keys(data, CLARIFICATION_KEYS, "clarification specification")
    questions = _require_text_list(
        data, "questions", 1, MAX_CLARIFICATION_QUESTIONS, MAX_QUESTION_CHARS
    )
    outcome = SpecOutcome(questions=questions)
    if len(outcome.render()) > MAX_CLARIFICATION_CHARS:
        raise InvalidSpecificationError(
            f"rendered clarification must be at most {MAX_CLARIFICATION_CHARS} characters"
        )
    return outcome


def _require_criteria(data: dict[str, object], ticket: Ticket) -> tuple[AcceptanceCriterion, ...]:
    """Validate the acceptance criteria, their order, uniqueness and traceability."""
    raw_criteria = data.get("acceptance_criteria")
    if not isinstance(raw_criteria, list):
        raise InvalidSpecificationError("acceptance_criteria must be a list")
    if not MIN_ACCEPTANCE_CRITERIA <= len(raw_criteria) <= MAX_ACCEPTANCE_CRITERIA:
        raise InvalidSpecificationError(
            f"acceptance_criteria must contain between {MIN_ACCEPTANCE_CRITERIA} and "
            f"{MAX_ACCEPTANCE_CRITERIA} items"
        )
    ticket_text = _normalize_whitespace(f"{ticket.title}\n{ticket.description}")
    seen_statements: set[str] = set()
    return tuple(
        _require_criterion(index, raw_criterion, ticket_text, seen_statements)
        for index, raw_criterion in enumerate(raw_criteria, start=1)
    )


def _require_criterion(
    index: int,
    raw_criterion: object,
    ticket_text: str,
    seen_statements: set[str],
) -> AcceptanceCriterion:
    """Validate one acceptance criterion and its verbatim ticket quote."""
    prefix = f"acceptance_criteria[{index - 1}]"
    data = _require_object(raw_criterion, prefix)
    _require_exact_keys(data, ACCEPTANCE_CRITERION_KEYS, prefix)
    expected_id = f"AC{index}"
    criterion_id = data.get("id")
    if not isinstance(criterion_id, str):
        raise InvalidSpecificationError(f"{prefix}.id must be a string")
    if criterion_id != expected_id:
        raise InvalidSpecificationError(f"{prefix}.id must be {expected_id}")
    statement = _require_text(data, "statement", MAX_AC_STATEMENT_CHARS, prefix)
    statement_key = _normalize_whitespace(statement).casefold()
    if statement_key in seen_statements:
        raise InvalidSpecificationError(f"{prefix}.statement duplicates an earlier criterion")
    seen_statements.add(statement_key)
    ticket_quote = _require_text(data, "ticket_quote", MAX_TICKET_QUOTE_CHARS, prefix)
    if _normalize_whitespace(ticket_quote) not in ticket_text:
        raise InvalidSpecificationError(f"{prefix}.ticket_quote must quote the ticket verbatim")
    return AcceptanceCriterion(id=criterion_id, statement=statement, ticket_quote=ticket_quote)


def _require_object(payload: object, name: str) -> dict[str, object]:
    """Require a JSON object."""
    if not isinstance(payload, dict):
        raise InvalidSpecificationError(f"{name} must be a JSON object")
    return payload


def _require_exact_keys(data: dict[str, object], expected: frozenset[str], name: str) -> None:
    """Require exactly the expected keys, refusing unknown ones."""
    missing = sorted(expected - data.keys())
    unknown = sorted(str(key) for key in data.keys() - expected)
    if missing:
        raise InvalidSpecificationError(f"{name} is missing keys: {', '.join(missing)}")
    if unknown:
        raise InvalidSpecificationError(f"{name} has unknown keys: {', '.join(unknown)}")


def _require_text(data: dict[str, object], name: str, max_chars: int, prefix: str = "") -> str:
    """Require a non-blank string within its character bound."""
    field = f"{prefix}.{name}" if prefix else name
    value = data.get(name)
    if not isinstance(value, str):
        raise InvalidSpecificationError(f"{field} must be a string")
    if not value.strip():
        raise InvalidSpecificationError(f"{field} must not be blank")
    if len(value) > max_chars:
        raise InvalidSpecificationError(f"{field} must be at most {max_chars} characters")
    return value


def _require_text_list(
    data: dict[str, object],
    name: str,
    minimum: int,
    maximum: int,
    max_chars: int,
) -> tuple[str, ...]:
    """Require a list of non-blank strings within its size and item bounds."""
    value = data.get(name)
    if not isinstance(value, list):
        raise InvalidSpecificationError(f"{name} must be a list")
    if not minimum <= len(value) <= maximum:
        raise InvalidSpecificationError(
            f"{name} must contain between {minimum} and {maximum} items"
        )
    return tuple(
        _require_list_item(item, f"{name}[{index}]", max_chars) for index, item in enumerate(value)
    )


def _require_list_item(item: object, name: str, max_chars: int) -> str:
    """Require one non-blank string list item within its character bound."""
    if not isinstance(item, str):
        raise InvalidSpecificationError(f"{name} must be a string")
    if not item.strip():
        raise InvalidSpecificationError(f"{name} must not be blank")
    if len(item) > max_chars:
        raise InvalidSpecificationError(f"{name} must be at most {max_chars} characters")
    return item


def _normalize_whitespace(text: str) -> str:
    """Collapse every whitespace run into a single space."""
    return " ".join(text.split())
