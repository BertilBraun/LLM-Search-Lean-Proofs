from collections.abc import Sequence

import pytest

from lean_search.data_rewrite.naming import (
    Binder,
    Hypothesis,
    NameChange,
    NameRejection,
    NameSource,
    NamingConfig,
    NamingRequest,
    NamingSubject,
    RenamingStatus,
    RuleBasedNamer,
    choose_names,
    have_hypotheses,
    name_rejection,
    plan_renamings,
    renamed_text,
    rule_based_name,
    statement_binders,
    statement_hypotheses,
    unique_name,
)

CONFIG = NamingConfig()
STATEMENT = "theorem test (x y : ℝ) (h₀ : 0 < x) (h₁ : x + y = 3) : x < 3 := by"


class ScriptedNamer:
    """Proposes fixed names per hypothesis name and records how many requests it got."""

    source = NameSource.MODEL

    def __init__(self, names: dict[str, str]) -> None:
        self.names = names
        self.requests: list[NamingRequest] = []

    async def propose(self, requests: Sequence[NamingRequest]) -> list[tuple[str, ...]]:
        self.requests += requests
        return [tuple(self.names.get(hypothesis.name, "") for hypothesis in request.hypotheses) for request in requests]


def change(old: str, new: str) -> NameChange:
    return NameChange(old, new, NameSource.RULES)


def test_statement_binders_split_groups_into_names() -> None:
    statement = "theorem t {a b : ℕ} [Fact (1 < a)] (h h₂ : a = b)\n  (f : ℕ → ℕ) : f a = f b := by"
    assert statement_binders(statement) == (
        Binder("a", "ℕ"),
        Binder("b", "ℕ"),
        Binder("h", "a = b"),
        Binder("h₂", "a = b"),
        Binder("f", "ℕ → ℕ"),
    )


def test_statement_without_binders_has_none() -> None:
    assert statement_binders("theorem t : ∀ x : ℕ, x = x := by") == ()


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (STATEMENT, ["h₀", "h₁"]),
        ("theorem t (b h v : ℝ) (h₀ : 0 < b) : v = v := by", ["h₀"]),
        ("theorem t (a : ℝ) (h : 0 < a) (hab : a = 1) : a = 1 := by", ["h"]),
        ("theorem t (p : ℕ) (h₁ : Nat.Prime p) : p = p := by", ["h₁"]),
    ],
)
def test_statement_hypotheses_are_numbered_or_propositional_h(statement: str, expected: list[str]) -> None:
    assert [hypothesis.name for hypothesis in statement_hypotheses(statement, CONFIG)] == expected


def test_have_hypotheses_finds_flat_and_nested_haves() -> None:
    tactics = ("have h₂ : x < 3", "linarith", "· have h₃ : y = 3 - x := by linarith\n  linarith", "have hy : y = 1")
    assert have_hypotheses(tactics, CONFIG) == (Hypothesis("h₂", "x < 3"), Hypothesis("h₃", "y = 3 - x"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("linarith [h₀, h₁]", "linarith [hx_pos, hxy]"),
        ("exact h₀.le", "exact hx_pos.le"),
        ("exact h₀'", "exact h₀'"),
        ("exact h₁₀", "exact h₁₀"),
        ("exact foo.h₀", "exact foo.h₀"),
        ("From `h₀` and h₁, x < 3.", "From `hx_pos` and hxy, x < 3."),
        ("h₀ : 0 < x\n⊢ x < 3", "hx_pos : 0 < x\n⊢ x < 3"),
    ],
)
def test_renamed_text_replaces_whole_identifiers(text: str, expected: str) -> None:
    assert renamed_text(text, [change("h₀", "hx_pos"), change("h₁", "hxy")]) == expected


@pytest.mark.parametrize(
    ("type_text", "variables", "expected"),
    [
        ("0 < x", ["x"], "hx_pos"),
        ("x > 0", ["x"], "hx_pos"),
        ("x ≠ 0", ["x"], "hx_ne_zero"),
        ("0 ≤ a", ["a"], "ha_nonneg"),
        ("a + b + c = 1", ["a", "b", "c"], "habc"),
        ("a 0 = 1", ["a"], "ha0"),
        ("∀ x, f x = 2 * x + 3", ["f"], "hf"),
        ("Nat.Prime p", ["p"], "hp_prime"),
        ("¬p ∣ a", ["p", "a"], "hpa_not_dvd"),
        ("0 < x ∧ 0 < y ∧ 0 < z", ["x", "y", "z"], "hxyz_pos"),
        ("a ≤ b", ["a", "b"], "hab_le"),
        ("2 ≤ 3", [], "h_le"),
        ("p 1", [], "h_fact"),
    ],
)
def test_rule_based_names_describe_the_type(type_text: str, variables: list[str], expected: str) -> None:
    assert rule_based_name(type_text, variables, CONFIG) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("", NameRejection.MISSING),
        ("x_pos", NameRejection.NOT_A_NAME),
        ("hx-pos", NameRejection.NOT_A_NAME),
        ("hₓ", NameRejection.NOT_A_NAME),
        ("hx_", NameRejection.NOT_A_NAME),
        ("h1", NameRejection.NUMBERED),
        ("h", NameRejection.NUMBERED),
        ("h_" + "a" * 30, NameRejection.TOO_LONG),
        ("have", NameRejection.RESERVED),
        ("hx", NameRejection.TAKEN),
        ("hx_pos", None),
    ],
)
def test_name_rejection(name: str, expected: NameRejection | None) -> None:
    assert name_rejection(name, {"hx"}, frozenset(), CONFIG) == expected


def test_reserved_environment_names_are_rejected() -> None:
    assert name_rejection("hne", set(), frozenset({"hne"}), CONFIG) is NameRejection.RESERVED


def test_unique_name_appends_a_counter() -> None:
    assert unique_name("hx", {"hx", "hx_2"}, frozenset()) == "hx_3"


def request_of(statement: str) -> NamingRequest:
    hypotheses = statement_hypotheses(statement, CONFIG)
    return NamingRequest(statement, hypotheses, ("x", "y"), frozenset({"x", "y", "h₀", "h₁", "test"}))


def test_invalid_model_names_fall_back_to_rules_with_the_reason() -> None:
    changes = choose_names(request_of(STATEMENT), ("hx_pos", "h₁"), NameSource.MODEL, CONFIG)
    assert changes == (
        NameChange("h₀", "hx_pos", NameSource.MODEL),
        NameChange("h₁", "hxy", NameSource.RULES, NameRejection.NOT_A_NAME),
    )


def test_duplicate_model_names_fall_back_for_the_second() -> None:
    changes = choose_names(request_of(STATEMENT), ("h_sum", "h_sum"), NameSource.MODEL, CONFIG)
    assert [(item.new, item.rejection) for item in changes] == [("h_sum", None), ("hxy", NameRejection.TAKEN)]


async def test_statement_names_are_asked_once_per_statement() -> None:
    namer = ScriptedNamer({"h₀": "hx_pos", "h₁": "h_sum"})
    subjects = [NamingSubject(STATEMENT, ("linarith",)), NamingSubject(STATEMENT, ("nlinarith [h₀]",))]
    await plan_renamings(subjects, namer, CONFIG)
    assert len(namer.requests) == 1


async def test_have_names_are_renamed_with_the_statement_names() -> None:
    namer = ScriptedNamer({"h₀": "hx_pos", "h₁": "h_sum", "h₂": "hx_lt"})
    (renaming,) = await plan_renamings(
        [NamingSubject(STATEMENT, ("have h₂ : x < 3", "linarith", "exact h₂"))], namer, CONFIG
    )
    assert [(item.old, item.new) for item in renaming.changes] == [("h₀", "hx_pos"), ("h₁", "h_sum"), ("h₂", "hx_lt")]


async def test_statement_name_conflicting_with_the_proof_text_is_a_conflict() -> None:
    namer = ScriptedNamer({"h₀": "hx_pos", "h₁": "h_sum"})
    (renaming,) = await plan_renamings([NamingSubject(STATEMENT, ("intro hx_pos", "linarith"))], namer, CONFIG)
    assert renaming.status is RenamingStatus.NAME_CONFLICT


async def test_have_shadowing_a_statement_hypothesis_takes_its_new_name() -> None:
    namer = ScriptedNamer({"h₀": "hx_pos", "h₁": "h_sum", "h₂": "hx_lt"})
    tactics = ("have h₀ : 0 ≤ x := le_of_lt h₀", "linarith")
    (renaming,) = await plan_renamings([NamingSubject(STATEMENT, tactics)], namer, CONFIG)
    assert [change.old for change in renaming.changes] == ["h₀", "h₁"]


async def test_have_name_bound_twice_stays_numbered() -> None:
    namer = ScriptedNamer({"h₀": "hx_pos", "h₁": "h_sum", "h₂": "hx_lt", "h₃": "hy"})
    tactics = ("have h₂ : x < 3", "linarith", "rcases foo with h₂ | h₂", "have h₃ : y = 3 - x", "linarith")
    (renaming,) = await plan_renamings([NamingSubject(STATEMENT, tactics)], namer, CONFIG)
    assert [change.old for change in renaming.have_changes] == ["h₃"]


async def test_statement_without_numbered_hypotheses_has_nothing_to_rename() -> None:
    subject = NamingSubject("theorem t (x : ℝ) (hx : 0 < x) : x > 0 := by", ("exact hx",))
    (renaming,) = await plan_renamings([subject], RuleBasedNamer(CONFIG), CONFIG)
    assert renaming.status is RenamingStatus.NOTHING_TO_RENAME


async def test_rule_based_namer_names_have_hypotheses_by_proof_variables() -> None:
    subject = NamingSubject(
        "theorem t : ∀ x : ℝ, x ^ 2 ≥ 0 := by", ("intro x", "have h₁ : 0 ≤ x ^ 2", "positivity", "linarith")
    )
    (renaming,) = await plan_renamings([subject], RuleBasedNamer(CONFIG), CONFIG)
    assert renaming.changes == (NameChange("h₁", "hx_nonneg", NameSource.RULES),)
