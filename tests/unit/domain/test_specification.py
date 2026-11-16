"""Behavior tests for the specification artifact and its deterministic validator (spec 06e)."""

import dataclasses
import re

import pytest

from ai_factory.domain import specification as specification_module
from ai_factory.domain.errors import InvalidSpecificationError
from ai_factory.domain.specification import (
    MAX_AC_STATEMENT_CHARS,
    MAX_ACCEPTANCE_CRITERIA,
    MAX_CLARIFICATION_QUESTIONS,
    MAX_DEFINITION_OF_DONE_ITEMS,
    MAX_PROBLEM_CHARS,
    MAX_SCOPE_ITEM_CHARS,
    MAX_SCOPE_ITEMS,
    MAX_UNKNOWNS,
    AcceptanceCriterion,
    Specification,
    SpecOutcome,
    validate_spec_outcome,
)
from ai_factory.domain.ticket import Ticket


def _make_ticket() -> Ticket:
    return Ticket(
        ticket_id="42",
        title="Add the export endpoint",
        description="Export the data as CSV.\nThe header must list the columns.",
    )


def _criterion(index: int, statement: str | None = None) -> dict[str, object]:
    return {
        "id": f"AC{index}",
        "statement": statement or f"Criterion {index} is observable.",
        "ticket_quote": "Export the data as CSV.",
    }


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ready",
        "problem": "The factory cannot export the data.",
        "scope_in": ["Export the data as CSV."],
        "scope_out": ["Change the storage format."],
        "acceptance_criteria": [_criterion(1)],
        "unknowns": ["The column order is the storage order."],
        "definition_of_done": ["The export is tested."],
    }
    payload.update(overrides)
    return payload


def _make_specification() -> Specification:
    return Specification(
        problem="The factory cannot export the data.",
        scope_in=("Export the data as CSV.",),
        scope_out=("Change the storage format.",),
        acceptance_criteria=(
            AcceptanceCriterion(
                id="AC1",
                statement="The data is exported as CSV.",
                ticket_quote="Export the data as CSV.",
            ),
        ),
        unknowns=("The column order is the storage order.",),
        definition_of_done=("The export is tested.",),
    )


def _invalid_ready_payloads() -> list[dict[str, object]]:
    """Every malformed ready payload the validator must refuse."""
    missing_key = _payload()
    del missing_key["problem"]
    unknown_key = _payload()
    unknown_key["extra"] = "unexpected"
    wrong_criterion_key = _payload(acceptance_criteria=[{**_criterion(1), "extra": "unexpected"}])
    missing_criterion_key = _payload(
        acceptance_criteria=[{"id": "AC1", "statement": "Criterion is observable."}]
    )
    return [
        _payload(status="draft"),
        _payload(problem=42),
        _payload(problem="   "),
        _payload(problem="x" * (MAX_PROBLEM_CHARS + 1)),
        _payload(scope_in="Export the data."),
        _payload(scope_in=[]),
        _payload(scope_in=[f"Item {index}" for index in range(MAX_SCOPE_ITEMS + 1)]),
        _payload(scope_in=[42]),
        _payload(scope_in=[" "]),
        _payload(scope_in=["x" * (MAX_SCOPE_ITEM_CHARS + 1)]),
        _payload(scope_out=[f"Out {index}" for index in range(MAX_SCOPE_ITEMS + 1)]),
        _payload(acceptance_criteria={}),
        _payload(acceptance_criteria=[]),
        _payload(
            acceptance_criteria=[
                _criterion(index) for index in range(1, MAX_ACCEPTANCE_CRITERIA + 2)
            ]
        ),
        _payload(acceptance_criteria=[{**_criterion(1), "id": "AC2"}]),
        _payload(
            acceptance_criteria=[
                _criterion(1),
                _criterion(2, statement="  criterion   1 IS observable. "),
            ]
        ),
        _payload(acceptance_criteria=[{**_criterion(1), "ticket_quote": "Not in the ticket."}]),
        _payload(
            acceptance_criteria=[{**_criterion(1), "ticket_quote": "export the data as csv."}]
        ),
        _payload(acceptance_criteria=[_criterion(1, statement="x" * (MAX_AC_STATEMENT_CHARS + 1))]),
        _payload(acceptance_criteria=[{**_criterion(1), "statement": " "}]),
        _payload(acceptance_criteria=[{**_criterion(1), "ticket_quote": " "}]),
        _payload(acceptance_criteria=["not an object"]),
        _payload(acceptance_criteria=[{**_criterion(1), "id": 1}]),
        _payload(acceptance_criteria=[{**_criterion(1), "statement": 1}]),
        _payload(acceptance_criteria=[{**_criterion(1), "ticket_quote": 1}]),
        wrong_criterion_key,
        missing_criterion_key,
        _payload(unknowns=[f"Unknown {index}" for index in range(MAX_UNKNOWNS + 1)]),
        _payload(unknowns=[" "]),
        _payload(definition_of_done=[]),
        _payload(
            definition_of_done=[
                f"Done {index}" for index in range(MAX_DEFINITION_OF_DONE_ITEMS + 1)
            ]
        ),
        _payload(definition_of_done=["x" * (MAX_SCOPE_ITEM_CHARS + 1)]),
        missing_key,
        unknown_key,
    ]


def test_spec06e_ac3_value_objects_are_frozen_with_the_exact_fields() -> None:
    """AC3: the artifact is immutable and exposes exactly the contract fields."""
    specification = _make_specification()

    assert [field.name for field in dataclasses.fields(AcceptanceCriterion)] == [
        "id",
        "statement",
        "ticket_quote",
    ]
    assert [field.name for field in dataclasses.fields(Specification)] == [
        "problem",
        "scope_in",
        "scope_out",
        "acceptance_criteria",
        "unknowns",
        "definition_of_done",
    ]
    assert [field.name for field in dataclasses.fields(SpecOutcome)] == [
        "specification",
        "questions",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        specification.__setattr__("problem", "hijacked")
    with pytest.raises(dataclasses.FrozenInstanceError):
        specification.acceptance_criteria[0].__setattr__("statement", "hijacked")


def test_spec06e_ac3_outcome_carries_exactly_one_mode() -> None:
    """AC3: an outcome holds either a specification or questions, never both or neither."""
    with pytest.raises(InvalidSpecificationError):
        SpecOutcome()
    with pytest.raises(InvalidSpecificationError):
        SpecOutcome(specification=_make_specification(), questions=("Which format?",))

    assert SpecOutcome(specification=_make_specification()).questions == ()
    assert SpecOutcome(questions=("Which format?",)).specification is None


def test_spec06e_ac3_render_is_deterministic_and_ordered() -> None:
    """AC3: every field is rendered under fixed headers in a stable order."""
    specification = _make_specification()

    first_render = specification.render()
    second_render = specification.render()

    assert first_render == second_render
    headers = [
        "PROBLEM:",
        "SCOPE IN:",
        "SCOPE OUT:",
        "ACCEPTANCE CRITERIA:",
        "UNKNOWNS:",
        "DEFINITION OF DONE:",
    ]
    positions = [first_render.index(header) for header in headers]
    assert positions == sorted(positions)
    for value in (
        specification.problem,
        specification.scope_in[0],
        specification.scope_out[0],
        specification.acceptance_criteria[0].statement,
        specification.acceptance_criteria[0].ticket_quote,
        specification.unknowns[0],
        specification.definition_of_done[0],
    ):
        assert value in first_render


def test_spec06e_ac3_outcome_render_matches_its_mode() -> None:
    """AC3: a ready outcome renders the specification, a clarification its questions."""
    ready = SpecOutcome(specification=_make_specification())
    clarification = SpecOutcome(questions=("Which format?", "Which columns?"))

    assert ready.render() == _make_specification().render()
    assert clarification.render().startswith("CLARIFICATION QUESTIONS:")
    assert "- Which format?" in clarification.render()
    assert "- Which columns?" in clarification.render()


def test_spec06e_ac4_accepts_a_valid_ready_payload() -> None:
    """AC4: a valid ready payload becomes an equivalent specification."""
    outcome = validate_spec_outcome(_payload(), _make_ticket())

    assert outcome.specification is not None
    assert outcome.questions == ()
    assert outcome.specification.problem == "The factory cannot export the data."
    assert outcome.specification.acceptance_criteria == (
        AcceptanceCriterion(
            id="AC1",
            statement="Criterion 1 is observable.",
            ticket_quote="Export the data as CSV.",
        ),
    )


def test_spec06e_ac4_accepts_every_bound_at_its_maximum() -> None:
    """AC4: 20 ACs, 15 scope items, 10 unknowns and 10 DoD items are accepted."""
    payload = _payload(
        scope_in=[f"Scope {index}" for index in range(MAX_SCOPE_ITEMS)],
        scope_out=[f"Out {index}" for index in range(MAX_SCOPE_ITEMS)],
        acceptance_criteria=[_criterion(index) for index in range(1, MAX_ACCEPTANCE_CRITERIA + 1)],
        unknowns=[f"Unknown {index}" for index in range(MAX_UNKNOWNS)],
        definition_of_done=[f"Done {index}" for index in range(MAX_DEFINITION_OF_DONE_ITEMS)],
    )

    outcome = validate_spec_outcome(payload, _make_ticket())

    assert outcome.specification is not None
    assert len(outcome.specification.acceptance_criteria) == MAX_ACCEPTANCE_CRITERIA
    assert len(outcome.specification.scope_in) == MAX_SCOPE_ITEMS
    assert len(outcome.specification.unknowns) == MAX_UNKNOWNS


def test_spec06e_ac4_quote_is_matched_after_whitespace_normalization() -> None:
    """AC4: a quote with collapsed whitespace still matches the ticket verbatim."""
    ticket = Ticket(
        ticket_id="42",
        title="Add the export endpoint",
        description="Export   the data\nas CSV.",
    )
    payload = _payload(
        acceptance_criteria=[{**_criterion(1), "ticket_quote": "Export the data as CSV."}]
    )

    outcome = validate_spec_outcome(payload, ticket)

    assert outcome.specification is not None
    assert outcome.specification.acceptance_criteria[0].ticket_quote == ("Export the data as CSV.")


def test_spec06e_ac4_quote_may_come_from_the_title() -> None:
    """AC4: the traceable text is the title plus the description."""
    payload = _payload(
        acceptance_criteria=[{**_criterion(1), "ticket_quote": "Add the export endpoint"}]
    )

    outcome = validate_spec_outcome(payload, _make_ticket())

    assert outcome.specification is not None
    assert outcome.specification.acceptance_criteria[0].ticket_quote == ("Add the export endpoint")


@pytest.mark.parametrize("payload", [None, [], "text", 42])
def test_spec06e_ac5_rejects_a_non_object_payload(payload: object) -> None:
    """AC5: the validator only accepts a JSON object."""
    with pytest.raises(InvalidSpecificationError, match="JSON object"):
        validate_spec_outcome(payload, _make_ticket())


@pytest.mark.parametrize("payload", _invalid_ready_payloads())
def test_spec06e_ac5_rejects_every_malformed_ready_payload(
    payload: dict[str, object],
) -> None:
    """AC5: malformed ready payloads are refused, never guessed or repaired."""
    with pytest.raises(InvalidSpecificationError):
        validate_spec_outcome(payload, _make_ticket())


def test_spec06e_ac5_rejects_a_payload_over_the_total_bound() -> None:
    """AC5: a payload within every item bound can still exceed the total bound."""
    long_quote = "q" * MAX_AC_STATEMENT_CHARS
    ticket = Ticket(
        ticket_id="42",
        title="Add the export endpoint",
        description=long_quote,
    )
    payload = _payload(
        problem="p" * MAX_PROBLEM_CHARS,
        scope_in=["s" * MAX_SCOPE_ITEM_CHARS for _ in range(MAX_SCOPE_ITEMS)],
        acceptance_criteria=[
            {
                "id": f"AC{index}",
                "statement": f"{index:02d}" + "x" * (MAX_AC_STATEMENT_CHARS - 2),
                "ticket_quote": long_quote,
            }
            for index in range(1, MAX_ACCEPTANCE_CRITERIA + 1)
        ],
        unknowns=[],
        definition_of_done=["Done."],
    )

    with pytest.raises(InvalidSpecificationError, match="rendered specification"):
        validate_spec_outcome(payload, ticket)


def test_spec06e_ac5_error_names_the_faulty_field() -> None:
    """AC5: the failure points at the exact field and rule to fix."""
    payload = _payload(acceptance_criteria=[{**_criterion(1), "ticket_quote": "Paraphrased text."}])

    with pytest.raises(InvalidSpecificationError, match=r"acceptance_criteria\[0\]\.ticket_quote"):
        validate_spec_outcome(payload, _make_ticket())


def test_spec06e_ac6_accepts_valid_clarification() -> None:
    """AC6: one to five non-blank questions become a clarification outcome."""
    questions = ["Which export format?", "Which columns?"]

    outcome = validate_spec_outcome(
        {"status": "needs_clarification", "questions": questions},
        _make_ticket(),
    )

    assert outcome.specification is None
    assert outcome.questions == tuple(questions)


def test_spec06e_ac6_rejects_clarification_over_the_total_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: the total bound refuses a clarification even when every question fits.

    The production bound (2,000) sits above the maximum render of five 300-character
    questions, so the guard is exercised with a tight bound instead of dead code.
    """
    monkeypatch.setattr(specification_module, "MAX_CLARIFICATION_CHARS", 10)
    payload = {"status": "needs_clarification", "questions": ["Which export format?"]}

    with pytest.raises(InvalidSpecificationError, match="rendered clarification"):
        validate_spec_outcome(payload, _make_ticket())


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "needs_clarification", "questions": []},
        {
            "status": "needs_clarification",
            "questions": [f"Question {index}?" for index in range(MAX_CLARIFICATION_QUESTIONS + 1)],
        },
        {"status": "needs_clarification", "questions": [" "]},
        {"status": "needs_clarification", "questions": ["x" * 301]},
        {"status": "needs_clarification", "questions": "Which format?"},
        {"status": "needs_clarification", "questions": ["Which format?"], "extra": "x"},
        {"status": "needs_clarification"},
    ],
)
def test_spec06e_ac6_rejects_malformed_clarification(payload: dict[str, object]) -> None:
    """AC6: malformed clarification payloads are refused."""
    with pytest.raises(InvalidSpecificationError):
        validate_spec_outcome(payload, _make_ticket())


def _payload_with_render_length(target_length: int) -> tuple[dict[str, object], Ticket]:
    """Build a ready payload whose rendered specification has exactly target_length chars."""
    long_quote = "q" * 300
    ticket = Ticket(ticket_id="42", title="Add the export endpoint", description=long_quote)
    base_payload: dict[str, object] = {
        "status": "ready",
        "problem": "p",
        "scope_in": ["s" * 200 for _ in range(15)],
        "scope_out": ["o" * 200 for _ in range(15)],
        "acceptance_criteria": [
            {
                "id": f"AC{index}",
                "statement": f"{index:02d}" + "s" * 298,
                "ticket_quote": long_quote,
            }
            for index in range(1, 9)
        ],
        "unknowns": ["u" * 200 for _ in range(10)],
        "definition_of_done": ["d" * 200 for _ in range(10)],
    }
    base_outcome = validate_spec_outcome(base_payload, ticket)
    assert base_outcome.specification is not None
    base_length = len(base_outcome.specification.render())
    problem_length = target_length - base_length + 1
    assert 1 <= problem_length <= 1_500
    return {**base_payload, "problem": "p" * problem_length}, ticket


def test_spec06e_ac3_outcome_is_frozen() -> None:
    """AC3: the outcome is immutable like the artifact it carries."""
    outcome = SpecOutcome(specification=_make_specification())

    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.__setattr__("questions", ("Hijacked?",))


def test_spec06e_ac4_accepts_every_character_bound_at_its_exact_maximum() -> None:
    """AC4: each character bound accepts exactly its contractual maximum."""
    ticket = Ticket(ticket_id="42", title="Add the export endpoint", description="q" * 300)
    payload = _payload(
        problem="p" * 1_500,
        scope_in=["s" * 200],
        scope_out=["o" * 200],
        acceptance_criteria=[{"id": "AC1", "statement": "s" * 300, "ticket_quote": "q" * 300}],
        unknowns=["u" * 200],
        definition_of_done=["d" * 200],
    )

    outcome = validate_spec_outcome(payload, ticket)

    assert outcome.specification is not None
    specification = outcome.specification
    assert len(specification.problem) == 1_500
    assert len(specification.scope_in[0]) == 200
    assert len(specification.scope_out[0]) == 200
    assert len(specification.acceptance_criteria[0].statement) == 300
    assert len(specification.acceptance_criteria[0].ticket_quote) == 300
    assert len(specification.unknowns[0]) == 200
    assert len(specification.definition_of_done[0]) == 200


def test_spec06e_ac4_accepts_every_item_count_at_its_exact_maximum() -> None:
    """AC4: each list bound accepts exactly its contractual item count."""
    payload = _payload(
        scope_in=[f"Scope {index}" for index in range(15)],
        scope_out=[f"Out {index}" for index in range(15)],
        acceptance_criteria=[_criterion(index) for index in range(1, 21)],
        unknowns=[f"Unknown {index}" for index in range(10)],
        definition_of_done=[f"Done {index}" for index in range(10)],
    )

    outcome = validate_spec_outcome(payload, _make_ticket())

    assert outcome.specification is not None
    specification = outcome.specification
    assert len(specification.scope_in) == 15
    assert len(specification.scope_out) == 15
    assert len(specification.acceptance_criteria) == 20
    assert len(specification.unknowns) == 10
    assert len(specification.definition_of_done) == 10


def test_spec06e_ac4_accepts_an_empty_scope_out_and_no_unknowns() -> None:
    """AC4: the optional scope-out and unknowns lists may be empty."""
    outcome = validate_spec_outcome(_payload(scope_out=[], unknowns=[]), _make_ticket())

    assert outcome.specification is not None
    assert outcome.specification.scope_out == ()
    assert outcome.specification.unknowns == ()


def test_spec06e_ac4_accepts_a_specification_of_exactly_16000_characters() -> None:
    """AC4: the total render bound accepts exactly 16,000 characters."""
    payload, ticket = _payload_with_render_length(16_000)

    outcome = validate_spec_outcome(payload, ticket)

    assert outcome.specification is not None
    assert len(outcome.specification.render()) == 16_000


@pytest.mark.parametrize(
    "payload",
    [
        _payload(problem="x" * 1_501),
        _payload(scope_in=["x" * 201]),
        _payload(acceptance_criteria=[{**_criterion(1), "statement": "x" * 301}]),
        _payload(unknowns=["x" * 201]),
        _payload(definition_of_done=["x" * 201]),
    ],
)
def test_spec06e_ac5_rejects_one_character_above_each_item_bound(
    payload: dict[str, object],
) -> None:
    """AC5: one character above any item bound is refused."""
    with pytest.raises(InvalidSpecificationError):
        validate_spec_outcome(payload, _make_ticket())


def test_spec06e_ac5_rejects_a_ticket_quote_above_its_bound() -> None:
    """AC5: a 301-character quote is refused even when the ticket contains it."""
    ticket = Ticket(ticket_id="42", title="Add the export endpoint", description="q" * 301)
    payload = _payload(acceptance_criteria=[{**_criterion(1), "ticket_quote": "q" * 301}])

    with pytest.raises(
        InvalidSpecificationError,
        match=r"acceptance_criteria\[0\]\.ticket_quote must be at most 300",
    ):
        validate_spec_outcome(payload, ticket)


@pytest.mark.parametrize(
    "payload",
    [
        _payload(scope_in=[f"Scope {index}" for index in range(16)]),
        _payload(scope_out=[f"Out {index}" for index in range(16)]),
        _payload(acceptance_criteria=[_criterion(index) for index in range(1, 22)]),
        _payload(unknowns=[f"Unknown {index}" for index in range(11)]),
        _payload(definition_of_done=[f"Done {index}" for index in range(11)]),
    ],
)
def test_spec06e_ac5_rejects_one_item_above_each_count_bound(
    payload: dict[str, object],
) -> None:
    """AC5: one item above any list count bound is refused."""
    with pytest.raises(InvalidSpecificationError):
        validate_spec_outcome(payload, _make_ticket())


def test_spec06e_ac5_rejects_a_specification_of_16001_characters() -> None:
    """AC5: the total render bound refuses 16,001 characters."""
    payload, ticket = _payload_with_render_length(16_001)

    with pytest.raises(InvalidSpecificationError, match="rendered specification"):
        validate_spec_outcome(payload, ticket)


def test_spec06e_ac5_error_names_the_field_for_a_prefixed_bound_violation() -> None:
    """AC5: a criterion error carries its zero-based field path and exact bound."""
    payload = _payload(acceptance_criteria=[{**_criterion(1), "statement": "x" * 301}])

    with pytest.raises(
        InvalidSpecificationError,
        match=r"acceptance_criteria\[0\]\.statement must be at most 300 characters",
    ):
        validate_spec_outcome(payload, _make_ticket())


def test_spec06e_ac5_error_distinguishes_missing_from_unknown_keys() -> None:
    """AC5: a missing key and an unknown key produce distinct, actionable messages."""
    missing_payload = _payload()
    del missing_payload["problem"]
    unknown_payload = _payload(extra="unexpected")

    with pytest.raises(InvalidSpecificationError, match="missing keys: problem"):
        validate_spec_outcome(missing_payload, _make_ticket())
    with pytest.raises(InvalidSpecificationError, match="unknown keys: extra"):
        validate_spec_outcome(unknown_payload, _make_ticket())


def test_spec06e_ac5_rejects_an_unknown_status_with_a_valid_ready_payload() -> None:
    """AC5: the status is matched exactly, never by lexical ordering."""
    with pytest.raises(InvalidSpecificationError, match="status must be one of"):
        validate_spec_outcome(_payload(status="zzz"), _make_ticket())


@pytest.mark.parametrize(
    ("criterion_index", "field_prefix"),
    [
        (2, "acceptance_criteria[1]"),
        (3, "acceptance_criteria[2]"),
        (4, "acceptance_criteria[3]"),
    ],
)
def test_spec06e_ac5_error_prefix_uses_the_zero_based_criterion_index(
    criterion_index: int, field_prefix: str
) -> None:
    """AC5: the error path points at the failing criterion, not a computed neighbour."""
    criteria = [_criterion(index) for index in range(1, criterion_index + 1)]
    criteria[-1] = {**criteria[-1], "ticket_quote": "Paraphrased text."}

    with pytest.raises(InvalidSpecificationError, match=re.escape(f"{field_prefix}.ticket_quote")):
        validate_spec_outcome(_payload(acceptance_criteria=criteria), _make_ticket())


def test_spec06e_ac5_rejects_a_first_criterion_not_numbered_ac1() -> None:
    """AC5: criteria are numbered sequentially from AC1."""
    payload = _payload(acceptance_criteria=[{**_criterion(1), "id": "AC0"}])

    with pytest.raises(
        InvalidSpecificationError, match=r"acceptance_criteria\[0\]\.id must be AC1"
    ):
        validate_spec_outcome(payload, _make_ticket())


@pytest.mark.parametrize("question_count", [1, 5])
def test_spec06e_ac6_accepts_between_one_and_five_questions(question_count: int) -> None:
    """AC6: the clarification bound accepts one to five questions."""
    questions = [f"Question {index}?" for index in range(question_count)]

    outcome = validate_spec_outcome(
        {"status": "needs_clarification", "questions": questions}, _make_ticket()
    )

    assert outcome.questions == tuple(questions)


def test_spec06e_ac6_rejects_an_empty_question_list_with_the_count_rule() -> None:
    """AC6: an empty clarification is refused by the question count rule."""
    with pytest.raises(InvalidSpecificationError, match="between 1 and 5 items"):
        validate_spec_outcome({"status": "needs_clarification", "questions": []}, _make_ticket())


def test_spec06e_ac6_accepts_a_question_of_exactly_300_characters() -> None:
    """AC6: the question character bound accepts exactly 300 characters."""
    question = "q" * 300

    outcome = validate_spec_outcome(
        {"status": "needs_clarification", "questions": [question]}, _make_ticket()
    )

    assert outcome.questions == (question,)


def test_spec06e_ac6_rejects_an_unknown_status_with_a_valid_clarification_payload() -> None:
    """AC6: an unknown status is refused even when the clarification shape is valid."""
    with pytest.raises(InvalidSpecificationError, match="status must be one of"):
        validate_spec_outcome({"status": "zzz", "questions": ["Which format?"]}, _make_ticket())


def test_spec06e_ac6_rejects_a_status_below_the_known_values_with_a_valid_payload() -> None:
    """AC6: a status lexically below the known values is still refused."""
    with pytest.raises(InvalidSpecificationError, match="status must be one of"):
        validate_spec_outcome({"status": "aaa", "questions": ["Which format?"]}, _make_ticket())
