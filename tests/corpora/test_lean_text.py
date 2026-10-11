import pytest

from lean_search.corpora.lean_text import (
    DeclarationError,
    DeclarationParts,
    contains_incomplete_proof,
    declares_axiom,
    split_declaration,
    split_statement,
    split_top_level_tactics,
    strip_comments,
)

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"

GOEDEL_STYLE_PROOF = f"""{HEADER}

/- prove that $x^2 \\ge 0$ -/
theorem lean_workbook_1 (x : ℝ) (hx : 0 < x) :  x ^ 2 ≥ 0  := by
  /-
  We use non-negativity of squares.
  -/
  -- the main step
  nlinarith [sq_nonneg x,
    sq_nonneg (x - 1)]
"""


def parse(text: str, name: str | None = None) -> DeclarationParts:
    parts = split_declaration(text, name)
    assert isinstance(parts, DeclarationParts)
    return parts


def test_strip_comments_removes_line_and_nested_block_comments() -> None:
    text = "a -- trailing\n/- outer /- inner -/ still comment -/\nb"
    assert strip_comments(text) == "a\nb"


def test_strip_comments_keeps_column_of_code_after_inline_block_comment() -> None:
    assert strip_comments("  /- note -/ simp").index("simp") == len("  /- note -/ ")


def test_strip_comments_ignores_comment_markers_inside_strings() -> None:
    assert strip_comments('#eval "a -- b"') == '#eval "a -- b"'


def test_split_declaration_extracts_header_without_comments() -> None:
    assert parse(GOEDEL_STYLE_PROOF).header == HEADER


def test_split_declaration_ends_statement_with_by() -> None:
    expected = "theorem lean_workbook_1 (x : ℝ) (hx : 0 < x) :  x ^ 2 ≥ 0 := by"
    assert parse(GOEDEL_STYLE_PROOF).formal_statement == expected


def test_split_declaration_dedents_proof_and_drops_comments() -> None:
    expected = "nlinarith [sq_nonneg x,\n  sq_nonneg (x - 1)]"
    assert parse(GOEDEL_STYLE_PROOF).tactic_proof == expected


def test_split_declaration_skips_assignments_of_let_in_statement() -> None:
    text = "theorem thm_0 :\n  let h := (3 : ℝ) / 2;\n  h ≤ 2 := by\n  intro h\n  norm_num [h]"
    assert parse(text).tactic_proof == "intro h\nnorm_num [h]"


def test_split_declaration_ignores_assignments_inside_binders() -> None:
    text = "theorem foo (n : ℕ := 3) : n = n := by\n  rfl"
    assert parse(text).formal_statement == "theorem foo (n : ℕ := 3) : n = n := by"


def test_split_declaration_keeps_tactic_on_the_by_line() -> None:
    text = "theorem foo (x : ℝ) : x ^ 2 ≥ 0 := by nlinarith [sq_nonneg x,\n    sq_nonneg (x + 1)]"
    assert parse(text).tactic_proof == "nlinarith [sq_nonneg x,\n    sq_nonneg (x + 1)]"


def test_split_declaration_moves_following_commands_to_trailing_text() -> None:
    text = "theorem foo : 1 = 1 := by\n  rfl\n#print axioms foo"
    assert parse(text).trailing_text == "#print axioms foo"


def test_split_declaration_keeps_column_zero_lines_inside_brackets() -> None:
    text = "theorem foo : 1 = 1 := by\n  simp [one_mul,\nmul_one]"
    assert parse(text).tactic_proof == "simp [one_mul,\nmul_one]"


def test_split_declaration_prefers_the_named_theorem() -> None:
    text = "theorem aux : 2 = 2 := by\n  rfl\ntheorem main : 1 = 1 := by\n  norm_num"
    assert parse(text, "aux").tactic_proof == "rfl"


def test_split_declaration_defaults_to_the_last_declaration() -> None:
    text = "lemma aux : 2 = 2 := by\n  rfl\ntheorem main : 1 = 1 := by\n  norm_num"
    assert parse(text).formal_statement == "theorem main : 1 = 1 := by"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("theorem foo : 1 = 1 := rfl", DeclarationError.TERM_MODE),
        ("def foo : ℕ := 1", DeclarationError.NO_DECLARATION),
        ("theorem foo b c : ℝ) : b = c := by\n  simp", DeclarationError.NO_ASSIGNMENT),
    ],
)
def test_split_declaration_reports_unusable_declarations(text: str, error: DeclarationError) -> None:
    assert split_declaration(text) == error


def test_split_statement_accepts_term_mode_sorry() -> None:
    parts = split_statement("import Mathlib\ntheorem foo (n : ℕ) : n = n :=\nsorry")
    assert parts.formal_statement == "theorem foo (n : ℕ) : n = n := by"


@pytest.mark.parametrize(
    ("proof", "expected"),
    [
        ("simp\nring", ("simp", "ring")),
        ("nlinarith [a,\n  b]\nlinarith", ("nlinarith [a,\n  b]", "linarith")),
        ("have h : x = 1 := by\n  simp\nexact h", ("have h : x = 1 := by\n  simp", "exact h")),
        ("constructor\n· simp\n  ring\n· linarith", ("constructor", "· simp\n  ring", "· linarith")),
        ("cases h <;>\nsimp", ("cases h <;>\nsimp",)),
        ("norm_num\n<;> linarith", ("norm_num\n<;> linarith",)),
        (
            "induction n with\n| zero => simp\n| succ n ih => simp",
            ("induction n with\n| zero => simp\n| succ n ih => simp",),
        ),
        ("calc a = b := by simp\n_ = c := by ring", ("calc a = b := by simp\n_ = c := by ring",)),
        ("simp [foo,\nbar]\nring", ("simp [foo,\nbar]", "ring")),
    ],
)
def test_split_top_level_tactics(proof: str, expected: tuple[str, ...]) -> None:
    assert split_top_level_tactics(proof) == expected


@pytest.mark.parametrize(
    ("text", "incomplete"),
    [("simp\nsorry", True), ("admit", True), ("exact h_sorry", False), ("simp [sorryAx]", False)],
)
def test_contains_incomplete_proof(text: str, incomplete: bool) -> None:
    assert contains_incomplete_proof(text) == incomplete


def test_declares_axiom_detects_axiom_command() -> None:
    assert declares_axiom("import Mathlib\naxiom cheat : False")
