import numpy

from lean_search.expert_iteration.near_duplicates import MinHasher, SimilarPair, clusters, similar_pairs

ORIGINAL = "theorem a (x y : ℝ) (h₀ : 0 < x) (h₁ : 0 < y) (h₂ : x + y = 1) : x * y ≤ 1 / 4 := by"
RENAMED = "theorem b (a b : ℝ) (ha : 0 < a) (hb : 0 < b) (hab : a + b = 1) : a * b ≤ 1 / 4 := by"
DIFFERENT = "theorem c (n : ℕ) (h : n % 4 = 3) : ¬ ∃ a b : ℕ, a ^ 2 + b ^ 2 = n := by"


def signatures(*statements: str) -> numpy.ndarray:
    hasher = MinHasher()
    return numpy.stack([hasher.signature(statement) for statement in statements])


def test_a_renamed_formalization_is_a_near_duplicate() -> None:
    representatives = clusters(3, similar_pairs(signatures(ORIGINAL, DIFFERENT, RENAMED)), threshold=0.7)
    assert representatives == [0, 1, 0]


def test_a_cluster_keeps_its_first_member() -> None:
    pairs = [SimilarPair(2, 1, 0.9), SimilarPair(1, 0, 0.75), SimilarPair(3, 2, 0.5)]
    assert clusters(4, pairs, threshold=0.7) == [0, 0, 0, 3]
