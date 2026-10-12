import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.pool import (
    CANONICAL_IMPORTS,
    PrefilterOutcome,
    SourceQuota,
    canonical_header,
    completed_prefix,
    first_per_name,
    interleave,
    load_failure_category,
    ordering_key,
    prefilter_outcome,
    problem_name,
    problem_source,
    select_by_source,
)
from lean_search.search import Accounting, SearchResult, StopReason

SEED = "test"
LEAN_WORKBOOK_HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat"


def statement(source: str, number: int) -> StatementRecord:
    return StatementRecord(
        source, f"{source}_{number}", "import Mathlib", f"theorem t{number} : {number} = {number} := by", "", ""
    )


def statements(source: str, count: int) -> list[StatementRecord]:
    return [statement(source, number) for number in range(count)]


def never_excluded(_: StatementRecord) -> bool:
    return False


def result(stop_reason: StopReason, proved: bool) -> SearchResult:
    return SearchResult("p", proved, stop_reason, None, (), (), Accounting(), None, 0, 0)


def test_selection_keeps_the_first_statements_of_the_hash_order() -> None:
    pool = statements("a", 50)
    (selection,) = select_by_source(pool, [SourceQuota("a", 5)], SEED, never_excluded)
    expected = sorted(pool, key=lambda record: ordering_key(SEED, record))[:5]
    assert selection.ordered() == expected


def test_selection_does_not_depend_on_the_input_order() -> None:
    pool = statements("a", 50)
    (forward,) = select_by_source(pool, [SourceQuota("a", 5)], SEED, never_excluded)
    (backward,) = select_by_source(pool[::-1], [SourceQuota("a", 5)], SEED, never_excluded)
    assert forward.ordered() == backward.ordered()


def test_excluded_statements_are_never_selected() -> None:
    pool = statements("a", 20)
    (selection,) = select_by_source(pool, [SourceQuota("a", 20)], SEED, lambda record: record.identifier.endswith("7"))
    assert [record.identifier for record in selection.ordered() if record.identifier.endswith("7")] == []


def test_sources_without_a_quota_are_ignored() -> None:
    selections = select_by_source(statements("a", 3) + statements("b", 3), [SourceQuota("a", 10)], SEED, never_excluded)
    assert [selection.available for selection in selections] == [3]


def test_every_prefix_of_the_interleaving_is_proportional() -> None:
    merged = interleave([["a"] * 20, ["b"] * 10])
    assert all(abs(merged[:length].count("a") - 2 * merged[:length].count("b")) <= 2 for length in range(1, 31))


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("import Mathlib", f"{CANONICAL_IMPORTS}\n"),
        (LEAN_WORKBOOK_HEADER, LEAN_WORKBOOK_HEADER),
        (
            "import Mathlib\nimport Mathlib.Tactic.Ring\nopen Real",
            "import Mathlib\nimport Mathlib.Tactic.Ring\nopen Real",
        ),
    ],
)
def test_canonical_header_unifies_interchangeable_imports(header: str, expected: str) -> None:
    assert canonical_header(header) == expected


@pytest.mark.parametrize(
    ("search_result", "outcome"),
    [
        (result(StopReason.START_FAILED, False), PrefilterOutcome.LOAD_FAILED),
        (result(StopReason.PROVED, True), PrefilterOutcome.AUTOMATION_SOLVED),
        (result(StopReason.EXPANSION_BUDGET, False), PrefilterOutcome.UNSOLVED),
        (result(StopReason.FRONTIER_EXHAUSTED, False), PrefilterOutcome.UNSOLVED),
    ],
)
def test_prefilter_outcome(search_result: SearchResult, outcome: PrefilterOutcome) -> None:
    assert prefilter_outcome(search_result) == outcome


def test_completed_prefix_stops_at_the_first_statement_without_a_result() -> None:
    assert completed_prefix(["a", "b", "c", "d"], {"a", "b", "d"}) == 2


def test_load_failure_category_hides_names() -> None:
    assert load_failure_category("unknown identifier 'Real.foo'\nmore") == "unknown identifier '…'"


def test_problem_names_carry_the_source() -> None:
    assert problem_name(StatementRecord("numina", "a/b", "", "", "", "")) == "numina.a_b"


def test_only_the_first_statement_of_a_name_is_kept() -> None:
    first = statement("a", 1)
    second = StatementRecord("a", first.identifier, "", "theorem other : True := by", "", "")
    assert first_per_name([first, second, statement("a", 2)]) == ([first, statement("a", 2)], 1)


@pytest.mark.parametrize(
    ("name", "source"), [("lean_workbook.lean_workbook_7", "lean_workbook"), ("mathd_algebra_11", "other")]
)
def test_problem_source(name: str, source: str) -> None:
    assert problem_source(name) == source
