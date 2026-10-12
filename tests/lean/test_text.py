import pytest

from lean_search.lean.text import (
    HeaderParts,
    auxiliary_statement,
    executed_proof,
    find_forbidden_tokens,
    is_incomplete_input,
    lean_string_literal,
    lex,
    normalize_goal,
    split_header,
    split_tactics,
    theorem_name,
    theorem_with_proof,
    wrap_tactic,
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
        ("first\n| omega\n| simp", ["first\n| omega\n| simp"]),
        ("rcases h with ⟨x, hx⟩\nsimp", ["rcases h with ⟨x, hx⟩", "simp"]),
        ("if h : x = 0 then\n  simp\nelse\n  omega", ["if h : x = 0 then\n  simp\nelse\n  omega"]),
        ("exact hby\nsimp", ["exact hby", "simp"]),
    ],
)
def test_split_tactics_by_indentation(block: str, expected: list[str]) -> None:
    assert split_tactics(block) == expected


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("/- First substitute\nthen compute -/\nsubst h₀\nrfl", ["subst h₀", "rfl"]),
        ("simp /- start\nmore -/\nring", ["simp /- start\nmore -/", "ring"]),
        ("/- a\nb -/ simp\nring", ["simp", "ring"]),
        ("exact foo -- a ( in a comment\nsimp", ["exact foo -- a ( in a comment", "simp"]),
        ('trace "("\nsimp', ['trace "("', "simp"]),
    ],
)
def test_split_tactics_ignores_comments_and_strings(block: str, expected: list[str]) -> None:
    assert split_tactics(block) == expected


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("constructor <;>\nassumption", ["constructor <;>\nassumption"]),
        ("have h : a = 2 :=\nh₀\nomega", ["have h : a = 2 :=\nh₀", "omega"]),
        ("intro x\nexact fun y =>\ny", ["intro x", "exact fun y =>\ny"]),
        ("refine ⟨?_,\n?_⟩\n· simp", ["refine ⟨?_,\n?_⟩", "· simp"]),
    ],
)
def test_split_tactics_continues_after_a_trailing_continuation_token(block: str, expected: list[str]) -> None:
    assert split_tactics(block) == expected


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            "nlinarith [sq_nonneg (a - b),\nsq_nonneg (a + b)]",
            ["nlinarith [sq_nonneg (a - b),\nsq_nonneg (a + b)]"],
        ),
        (
            "nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)\n]",
            ["nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)\n]"],
        ),
        ("simp only [foo,\n\n  bar]\nring", ["simp only [foo,\n  bar]", "ring"]),
    ],
)
def test_split_tactics_continues_inside_open_brackets(block: str, expected: list[str]) -> None:
    assert split_tactics(block) == expected


def test_split_tactics_keeps_calc_steps_aligned_with_calc() -> None:
    block = "calc a + b = 2 + b := by rw [h₀]\n_ = 5 := by rw [h₁]"
    assert split_tactics(block) == [block]


def test_split_tactics_counts_tabs_as_indentation() -> None:
    assert split_tactics("intro x\n\tsimp at x") == ["intro x\n\tsimp at x"]


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
        ("apply?", ["apply?"]),
        ("exact?", ["exact?"]),
        ("simp?! [foo]", ["simp?!"]),
        ("hint", ["hint"]),
        ("slim_check", ["slim_check"]),
        ("sleep 1000", ["sleep"]),
        ("nlinarith [sq_nonneg (a - b)]", []),
        ("exact h_admitted", []),
        ("exact sorry_free", []),
        ("decide", []),
        ("simp [hint₀]", []),
    ],
)
def test_find_forbidden_tokens(tactic: str, expected: list[str]) -> None:
    assert find_forbidden_tokens(tactic) == expected


@pytest.mark.parametrize(
    "tactic",
    [
        "nlinarith -- no sorry needed",
        "-- sorry\nnlinarith",
        "/- sorry -/ nlinarith",
        "/- outer /- inner -/ sorry -/ simp",
        "/-- doc sorry -/ simp",
        "so/- -/rry",
        'trace "\\\\" -- sorry',
        "exact h' -- sorry",
    ],
)
def test_forbidden_tokens_in_comments_are_ignored(tactic: str) -> None:
    assert find_forbidden_tokens(tactic) == []


@pytest.mark.parametrize(
    "tactic",
    [
        "/- outer /- inner -/ -/ sorry",
        "/-/- -/ sorry",
        '"--" sorry',
        'trace "/-" ; sorry ; trace "-/"',
        'trace "\\"" ; sorry -- "',
        "exact '\"' ; sorry ; exact '\"'",
        "exact «--» sorry",
        'exact r"\\" sorry -- "',
        's!"{sorry}"',
        "simp <--sorry",
        "exact `(tactic| sorry) -- x",
        'trace "sorry"',
    ],
)
def test_forbidden_tokens_hidden_by_lexical_tricks_are_found(tactic: str) -> None:
    assert find_forbidden_tokens(tactic) == ["sorry"]


def test_an_empty_token_set_forbids_nothing() -> None:
    assert find_forbidden_tokens("sleep 1000", frozenset()) == []


@pytest.mark.parametrize("text", ["simp -- c", "exact h' -- c", "simp [h₀'] /- c -/", 'trace "a" -- c', "a--b"])
def test_lexer_is_exact_for_plain_tactics(text: str) -> None:
    assert lex(text).exact


@pytest.mark.parametrize("text", ["exact '('", "exact «x»", "exact `foo", 'exact s!"{x}"', "x <-- y", 'f("a")'])
def test_lexer_is_inexact_where_lean_might_lex_differently(text: str) -> None:
    assert not lex(text).exact


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("<input>:2:14: unexpected end of input; expected term", True),
        ("<input>:1:5: unterminated comment", True),
        ("unknown identifier 'foo'", False),
    ],
)
def test_is_incomplete_input(message: str, expected: bool) -> None:
    assert is_incomplete_input(message) == expected


def test_wrap_tactic_indents_the_tactic_under_the_heartbeat_wrapper() -> None:
    assert wrap_tactic("simp\nring", 100) == "lean_search_heartbeats 100 =>\n  simp\n  ring"


def test_executed_proof_wraps_every_step_with_its_own_limit() -> None:
    assert executed_proof(("simp", "omega"), (10, 0)) == (
        "lean_search_heartbeats 10 =>\n  simp\nlean_search_heartbeats 0 =>\n  omega"
    )


def test_lean_string_literal_escapes_quotes_and_backslashes() -> None:
    assert lean_string_literal('a "b" \\c\nd') == '"a \\"b\\" \\\\c\nd"'


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


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            "import Mathlib\nimport Aesop\nset_option maxHeartbeats 0\nopen Real",
            HeaderParts("import Mathlib\nimport Aesop", "set_option maxHeartbeats 0\nopen Real"),
        ),
        (
            "import  Mathlib -- all of it\n\nimport Aesop\n\nopen Nat\n",
            HeaderParts("import Mathlib\nimport Aesop", "\nopen Nat\n"),
        ),
        (
            "/- imports -/\nimport Mathlib\n/- opens -/\nopen Nat",
            HeaderParts("import Mathlib", "/- opens -/\nopen Nat"),
        ),
        ("import Mathlib\n", HeaderParts("import Mathlib", "")),
        ("open Nat\nimport Mathlib", HeaderParts("", "open Nat\nimport Mathlib")),
        ("", HeaderParts("", "")),
    ],
)
def test_split_header_separates_the_imports_from_the_commands(header: str, expected: HeaderParts) -> None:
    assert split_header(header) == expected


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            "theorem t (a : ℕ) (h : a = 2) : a + 1 = 3 := by",
            "theorem t.lean_search_auxiliaries (a : ℕ) (h : a = 2) : ( a + 1 = 3 \n) → True := fun _ => trivial",
        ),
        (
            "theorem t : ∀ x : ℕ, x = x :=",
            "theorem t.lean_search_auxiliaries : ( ∀ x : ℕ, x = x \n) → True := fun _ => trivial",
        ),
        (
            "/-- doc: x -/\nlemma t {S : Set (ℕ × ℕ)} (h : S = {(x, y) | x = y}) :\n"
            "  (1, 1) ∈ S := by -- proof: below\n",
            "/-- doc: x -/\nlemma t.lean_search_auxiliaries {S : Set (ℕ × ℕ)} (h : S = {(x, y) | x = y}) :"
            " (\n  (1, 1) ∈ S \n) → True := fun _ => trivial",
        ),
    ],
)
def test_auxiliary_statement_proves_only_true(statement: str, expected: str) -> None:
    assert auxiliary_statement(statement) == expected


@pytest.mark.parametrize("statement", ["theorem t := by", "def t : ℕ := 3", "theorem t : True"])
def test_auxiliary_statement_of_an_unreadable_statement_is_none(statement: str) -> None:
    assert auxiliary_statement(statement) is None
