import pytest

from lean_search.lean.hypotheses import (
    accessible_names,
    adds_only_redundant_hypotheses,
    goal_parts,
    has_inaccessible_names,
    hypothesis_names,
    is_reflexive,
    renaming_tactic,
)

SHADOWED = "x : ℕ → ℤ\nh₀ h₂✝ h₃✝ h₄ : True\nh₂ : x 1 = 2\nh₁₁ :\n  x 4 = 3\n⊢ x 5 = 1"


def test_hypothesis_names_follow_the_context_order() -> None:
    assert hypothesis_names(SHADOWED) == ["x", "h₀", "h₂✝", "h₃✝", "h₄", "h₂", "h₁₁"]


def test_hypothesis_names_skip_the_case_tag() -> None:
    assert hypothesis_names("case inl\nh : p\n⊢ q") == ["h"]


def test_inaccessible_names_get_fresh_suffixed_names() -> None:
    assert accessible_names(SHADOWED) == ["h₂_1", "h₃_1"]


def test_fresh_names_avoid_names_in_use() -> None:
    assert accessible_names("x_1 : ℕ\nx✝¹ x✝ : ℕ\n⊢ True") == ["x_2", "x_3"]


@pytest.mark.parametrize(
    ("goals", "expected"),
    [
        (("a✝ : ℕ\n⊢ a✝ = a✝",), "rename_i a_1"),
        (("⊢ True", "n✝ : ℕ\n⊢ n✝ = n✝"), "on_goal 2 => rename_i n_1"),
        (("a✝ : ℕ\n⊢ True", "b✝ : ℕ\n⊢ True"), "rename_i a_1\non_goal 2 => rename_i b_1"),
        (("x : ℕ\n⊢ x = x",), None),
    ],
)
def test_renaming_tactic(goals: tuple[str, ...], expected: str | None) -> None:
    assert renaming_tactic(goals) == expected


def test_inaccessible_names_are_detected_in_any_goal() -> None:
    assert has_inaccessible_names(("⊢ True", "a✝ : ℕ\n⊢ True"))


def test_goal_parts_give_one_type_per_name() -> None:
    assert goal_parts(SHADOWED).hypothesis_types == (
        "ℕ → ℤ",
        "True",
        "True",
        "True",
        "True",
        "x 1 = 2",
        "x 4 = 3",
    )


def test_goal_parts_join_a_wrapped_target() -> None:
    assert goal_parts("case h\nx : ℕ\n⊢ x +\n    1 = 2").target == "x + 1 = 2"


@pytest.mark.parametrize(
    ("proposition", "reflexive"),
    [("x + e = x + e", True), ("p ↔ p", True), ("x = y", False), ("f (a = a) = b", False), ("a = a = a", False)],
)
def test_is_reflexive(proposition: str, reflexive: bool) -> None:
    assert is_reflexive(proposition) is reflexive


CONTEXT = "x e : ℝ\nh₀ : x + e = 7\n⊢ e = 11"


@pytest.mark.parametrize(
    ("after", "redundant"),
    [
        (("x e : ℝ\nh₀ : x + e = 7\nh₄ : x + e = 7\n⊢ e = 11",), True),
        (("x e : ℝ\nh₀ : x + e = 7\nh₄ : x = x\n⊢ e = 11",), True),
        (("x e : ℝ\nh₀ : x + e = 7\n⊢ x + e = 7", "x e : ℝ\nh₀ : x + e = 7\nh₄ : x + e = 7\n⊢ e = 11"), True),
        (("x e : ℝ\nh₀ : x + e = 7\nh₁ : e = 7 - x\n⊢ e = 11",), False),
        (("x e : ℝ\nh₀ : x + e = 7\nh₄ : x + e = 7\n⊢ e = 7 - x",), False),
        (("x e : ℝ\nh₀ : x + e = 7\n⊢ e = 11",), False),
        (("x e : ℝ\nh₀✝ : x + e = 7\nh₀ : x + e = 7\n⊢ e = 11",), True),
    ],
    ids=["copy", "reflexive", "flattened have", "new fact", "target changed", "unchanged", "shadowing"],
)
def test_adds_only_redundant_hypotheses(after: tuple[str, ...], redundant: bool) -> None:
    assert adds_only_redundant_hypotheses((CONTEXT,), after) is redundant
