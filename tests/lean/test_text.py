import pytest

from lean_search.lean.text import (
    find_forbidden_tokens,
    normalize_goal,
    split_tactics,
    theorem_name,
    theorem_with_proof,
)


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("", []),
        ("omega", ["omega"]),
        ("intro x\nsimp", ["intro x", "simp"]),
        ("  intro x\n  simp", ["intro x", "simp"]),
        (
            "nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)]",
            ["nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)]"],
        ),
        ("have h : 0 < 2 := by\n  norm_num\nlinarith", ["have h : 0 < 2 := by\n  norm_num", "linarith"]),
        ("constructor\n· simp\n  ring\n· omega", ["constructor", "· simp\n  ring", "· omega"]),
        ("intro x\n\n-- a comment\nsimp", ["intro x", "simp"]),
        ("constructor\n<;> simp", ["constructor\n<;> simp"]),
        (
            "induction n with\n| zero => simp\n| succ n ih => omega",
            ["induction n with\n| zero => simp\n| succ n ih => omega"],
        ),
        ("calc a = b := by simp\n  _ = c := by ring", ["calc a = b := by simp\n  _ = c := by ring"]),
        ("    intro x\n      simp at x\n    exact x", ["intro x\n  simp at x", "exact x"]),
    ],
)
def test_split_tactics_by_indentation(block: str, expected: list[str]) -> None:
    assert split_tactics(block) == expected


@pytest.mark.parametrize(
    ("tactic", "expected"),
    [
        ("sorry", ["sorry"]),
        ("simp; admit", ["admit"]),
        ("exact sorryAx _ false", ["sorryAx"]),
        ("native_decide", ["native_decide"]),
        ("exact Lean.ofReduceBool _ _ rfl", ["ofReduceBool"]),
        ("set_option maxHeartbeats 0 in nlinarith", ["maxHeartbeats", "set_option"]),
        ("run_tac Lean.Elab.Tactic.evalTactic", ["run_tac"]),
        ("nlinarith [sq_nonneg (a - b)]", []),
        ("exact h_admitted", []),
        ("exact sorry_free", []),
        ("decide", []),
    ],
)
def test_find_forbidden_tokens(tactic: str, expected: list[str]) -> None:
    assert find_forbidden_tokens(tactic) == expected


def test_normalize_goal_collapses_whitespace_and_blank_lines() -> None:
    assert normalize_goal("x  y : ℕ\n\n⊢  x +  y = y + x ") == "x y : ℕ\n⊢ x + y = y + x"


def test_theorem_name_is_read_from_the_statement() -> None:
    assert theorem_name("theorem mathd_algebra_10 (x : ℝ) : x = x := by\n") == "mathd_algebra_10"


def test_theorem_with_proof_indents_the_proof_under_by() -> None:
    statement = "theorem t (x : ℕ) : x = x := by\n"
    assert theorem_with_proof(statement, "have h : x = x := by\n  rfl\nexact h") == (
        "theorem t (x : ℕ) : x = x := by\n  have h : x = x := by\n    rfl\n  exact h"
    )


def test_theorem_with_proof_adds_by_after_a_bare_definition_sign() -> None:
    assert theorem_with_proof("theorem t : True :=", "trivial") == "theorem t : True := by\n  trivial"


def test_theorem_with_proof_rejects_a_statement_without_proof_position() -> None:
    with pytest.raises(ValueError):
        theorem_with_proof("theorem t : True", "trivial")
