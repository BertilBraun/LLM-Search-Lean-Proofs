import pytest

from lean_search.corpora.decontamination import (
    ContaminationIndex,
    DecontaminationThresholds,
    MatchKind,
    ReferenceProblem,
    anonymized_statement_tokens,
    canonical_statement,
    conclusion_tokens,
    informal_tokens,
    jaccard_similarity,
    token_ngrams,
)

THRESHOLDS = DecontaminationThresholds(
    formal_ngram=0.35, shared_conclusion_formal_ngram=0.25, minimum_conclusion_tokens=5, informal_ngram=0.2
)
REFERENCES = (
    ReferenceProblem(
        "mathd_algebra_141",
        "test",
        "theorem mathd_algebra_141 (a b : ℝ) (h₁ : a * b = 180) (h₂ : 2 * (a + b) = 54) :\n"
        "    a ^ 2 + b ^ 2 = 369 := by\n",
        "/-- A rectangular patio has an area of $180$ square feet and a perimeter of $54$ feet. What is the "
        "length of the diagonal (in feet) squared? Show that it is 369.-/\n",
    ),
    ReferenceProblem(
        "amc12a_2009_p5",
        "valid",
        "theorem amc12a_2009_p5 (x : ℝ) (h₀ : x ^ 3 - (x + 1) * (x - 1) * x = 5) : x ^ 3 = 125 := by\n",
        "/-- One dimension of a cube is increased by $1$, another is decreased by $1$, and the third is left "
        "unchanged. The volume of the new rectangular solid is $5$ less than that of the cube. What was the "
        "volume of the cube? Show that it is 125.-/\n",
    ),
)


@pytest.fixture(scope="module")
def index() -> ContaminationIndex:
    return ContaminationIndex(REFERENCES, THRESHOLDS)


def test_canonical_statement_ignores_name_whitespace_and_proof() -> None:
    first = "theorem foo (x : ℝ)  (h : 0 < x) :\n  x ^ 2 > 0 := by\n  positivity"
    second = "theorem bar (x : ℝ) (h : 0 < x) : x ^ 2 > 0 := by sorry"
    assert canonical_statement(first) == canonical_statement(second)


def test_canonical_statement_ignores_spacing_around_symbols() -> None:
    assert canonical_statement("theorem a (x:ℝ): x^2 ≥ 0 := by") == canonical_statement(
        "theorem b (x : ℝ) : x ^ 2 ≥ 0 := by"
    )


def test_anonymized_tokens_rename_variables_in_order_and_collapse_hypotheses() -> None:
    tokens = anonymized_statement_tokens("theorem t (a b : ℕ) (hab : a < b) : ∀ c, a + c < b + c := by")
    assert " ".join(tokens) == "( v0 v1 : ℕ ) ( h : v0 < v1 ) : ∀ v2 , v0 + v2 < v1 + v2"


def test_anonymized_tokens_are_invariant_under_renaming() -> None:
    first = anonymized_statement_tokens("theorem t (x y : ℝ) (h₀ : x + y = 1) : x * y ≤ 1 / 4 := by")
    second = anonymized_statement_tokens("theorem s (a b : ℝ) (hab : a + b = 1) : a * b ≤ 1 / 4 := by")
    assert first == second


def test_conclusion_tokens_start_after_the_top_level_colon() -> None:
    tokens = anonymized_statement_tokens("theorem t (x : ℝ) (h : x = 2) : ∃ y : ℝ, y = x := by")
    assert conclusion_tokens(tokens) == ("∃", "v1", ":", "ℝ", ",", "v1", "=", "v0")


def test_token_ngrams_of_short_sequence_is_the_whole_sequence() -> None:
    assert token_ngrams(["a", "b"], 5) == frozenset({"a b"})


def test_jaccard_similarity_of_half_overlap() -> None:
    assert jaccard_similarity(frozenset({"a", "b", "c"}), frozenset({"b", "c", "d"})) == 0.5


def test_informal_tokens_drop_show_that_suffix_and_latex_formatting() -> None:
    assert informal_tokens("What is $\\textbf{(A)}\\ 2$? Show that it is 5.") == ["what", "is", "a", "2"]


def test_index_matches_identical_statement_exactly(index: ContaminationIndex) -> None:
    statement = "theorem other (a b : ℝ) (h₁ : a * b = 180) (h₂ : 2 * (a + b) = 54) : a ^ 2 + b ^ 2 = 369 := by"
    assert index.assess(statement, "").match.kind == MatchKind.EXACT


def test_index_matches_renamed_statement_by_ngrams(index: ContaminationIndex) -> None:
    statement = "theorem thm_916 (x y : ℝ) (h₀ : x * y = 180) (h₁ : 2 * x + 2 * y = 54) : x ^ 2 + y ^ 2 = 369 := by"
    assert index.assess(statement, "").match.kind == MatchKind.FORMAL_NGRAM


def test_index_matches_reformulated_hypotheses_with_shared_conclusion(index: ContaminationIndex) -> None:
    statement = "theorem alg (a : ℝ) (diff_vol : a ^ 3 - (a - 1) * a * (a + 1) = 5) : a ^ 3 = 125 := by"
    assert index.assess(statement, "").match.kind == MatchKind.SHARED_CONCLUSION


def test_index_matches_same_problem_by_informal_statement(index: ContaminationIndex) -> None:
    informal = (
        "A rectangular patio has an area of 180 square feet and a perimeter of 54 feet. What is the length of "
        "the diagonal (in feet) squared?"
    )
    statement = "theorem patio (l w : ℕ) (area : l * w = 180) (perimeter : l + w = 27) : l * l + w * w = 369 := by"
    assert index.assess(statement, informal).match.kind == MatchKind.INFORMAL_NGRAM


def test_index_keeps_unrelated_statement(index: ContaminationIndex) -> None:
    statement = "theorem other (n : ℕ) (h : 0 < n) : n ! ≥ 1 := by"
    assert index.assess(statement, "Prove that the factorial of a positive integer is positive.").match is None


@pytest.mark.parametrize(
    ("name", "kind"),
    [("amc12a_2009_p5", MatchKind.NAME), ("amc12a_2009_p5_variant", MatchKind.NAME), ("amc12a_2009_p50", None)],
)
def test_index_matches_benchmark_names_and_suffixed_variants(
    index: ContaminationIndex, name: str, kind: MatchKind | None
) -> None:
    match = index.assess(f"theorem {name} (n : ℕ) : n ! ≥ 1 := by", "").match
    assert (match.kind if match else None) == kind
