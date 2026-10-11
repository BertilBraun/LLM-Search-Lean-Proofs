import pytest

from lean_search.corpora.normalize import Rejection, normalize_proof, normalize_statement
from lean_search.corpora.records import ProofRecord, StatementRecord
from lean_search.corpora.sources import RawProof, RawStatement, comment_before_declaration, theorem_name

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat\n\n"


def raw_proof(proof_text: str, name: str | None = "foo") -> RawProof:
    return RawProof("test", "foo", name, HEADER + proof_text, "")


def normalized(proof_text: str, identifiers_unique: bool = True) -> ProofRecord:
    record = normalize_proof(raw_proof(proof_text), "test/0/0", "lean hint", identifiers_unique)
    assert isinstance(record, ProofRecord)
    return record


def test_normalize_proof_splits_statement_and_tactics() -> None:
    record = normalized("theorem foo (x : ℝ) : x ^ 2 ≥ 0 := by\n  have h := sq_nonneg x\n  linarith")
    assert (record.formal_statement, record.top_level_tactics()) == (
        "theorem foo (x : ℝ) : x ^ 2 ≥ 0 := by",
        ("have h := sq_nonneg x", "linarith"),
    )


def test_normalize_proof_keeps_header_for_tracing() -> None:
    assert normalized("theorem foo : 1 = 1 := by\n  rfl").header == HEADER.strip()


def test_normalize_proof_appends_statement_hash_when_names_are_not_unique() -> None:
    assert normalized("theorem foo : 1 = 1 := by\n  rfl", identifiers_unique=False).statement_identifier.startswith(
        "foo@"
    )


@pytest.mark.parametrize(
    ("proof_text", "rejection"),
    [
        ("theorem foo : 1 = 1 := by\n  sorry", Rejection.INCOMPLETE_PROOF),
        ("theorem foo : 1 = 1 := by\n  admit", Rejection.INCOMPLETE_PROOF),
        ("lemma aux : 2 = 2 := by sorry\ntheorem foo : 1 = 1 := by\n  rfl", Rejection.INCOMPLETE_PROOF),
        ("theorem foo : 1 = 1 := rfl", Rejection.TERM_MODE),
        ("theorem foo : 1 = 1 := by\n", Rejection.EMPTY_PROOF),
        ("axiom cheat : False\ntheorem foo : 1 = 1 := by\n  exact cheat.elim", Rejection.DECLARES_AXIOM),
        ("theorem foo : 1 = 1 := by\n  simp [one_mul", Rejection.UNBALANCED_BRACKETS),
        ("def foo : ℕ := 1", Rejection.NO_DECLARATION),
    ],
)
def test_normalize_proof_rejects_unusable_proofs(proof_text: str, rejection: Rejection) -> None:
    assert normalize_proof(raw_proof(proof_text), "test/0/0", "lean hint", True) == rejection


def test_normalize_statement_turns_sorry_statement_into_by_statement() -> None:
    raw = RawStatement("pool", "id-1", "foo", HEADER + "theorem foo (n : ℕ) : n + 0 = n := by sorry", "informal")
    record = normalize_statement(raw, "lean hint")
    assert isinstance(record, StatementRecord) and record.formal_statement == "theorem foo (n : ℕ) : n + 0 = n := by"


def test_normalize_statement_rejects_header_with_sorry_lemmas() -> None:
    text = "import Mathlib\nlemma helper : 1 < 2 := sorry\ntheorem foo : 2 < 3 := by"
    raw = RawStatement("pool", "id-1", "foo", text, "")
    assert normalize_statement(raw, "lean hint") == Rejection.INCOMPLETE_PROOF


def test_theorem_name_prefers_last_theorem_over_auxiliary_lemmas() -> None:
    text = "lemma helper : 1 < 2 := by norm_num\ntheorem main : 2 < 3 := by norm_num\nlemma after : 0 = 0 := rfl"
    assert theorem_name(text) == "main"


def test_comment_before_declaration_returns_docstring_text() -> None:
    text = "import Mathlib\n/-- What is $1+1$? Show that it is 2.-/\ntheorem foo : 1 + 1 = 2 := by\n  norm_num"
    assert comment_before_declaration(text) == "What is $1+1$? Show that it is 2."
