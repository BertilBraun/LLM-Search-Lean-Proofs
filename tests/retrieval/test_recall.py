import pytest

from lean_search.retrieval.recall import (
    RankedExample,
    RecallAtK,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    summarize_recall,
    transitive_imports,
)

RANKED = ("a", "b", "c", "d", "e")


@pytest.mark.parametrize(
    ("gold", "k", "recall"),
    [({"a"}, 1, 1.0), ({"b", "e"}, 2, 0.5), ({"b", "e"}, 5, 1.0), ({"z"}, 5, 0.0), ({"a", "z"}, 3, 0.5)],
)
def test_recall_at_k_is_the_fraction_of_gold_premises_in_the_top_k(gold: set[str], k: int, recall: float) -> None:
    assert recall_at_k(gold, RANKED, k) == recall


@pytest.mark.parametrize(("gold", "k", "hit"), [({"c", "z"}, 3, True), ({"c", "z"}, 2, False)])
def test_hit_needs_one_gold_premise_in_the_top_k(gold: set[str], k: int, hit: bool) -> None:
    assert hit_at_k(gold, RANKED, k) is hit


@pytest.mark.parametrize(("gold", "rank"), [({"a"}, 1.0), ({"z", "c"}, 1 / 3), ({"z"}, 0.0)])
def test_reciprocal_rank_of_the_first_gold_premise(gold: set[str], rank: float) -> None:
    assert reciprocal_rank(gold, RANKED) == rank


def test_summary_averages_over_states() -> None:
    examples = [RankedExample(frozenset({"a", "z"}), RANKED), RankedExample(frozenset({"c"}), RANKED)]
    summary = summarize_recall(examples, [1, 4])
    assert (summary.at_k, summary.mean_reciprocal_rank, summary.mean_gold_premises) == (
        (RecallAtK(1, 0.25, 0.5), RecallAtK(4, 0.75, 1.0)),
        (1.0 + 1 / 3) / 2,
        1.5,
    )


def test_transitive_imports_follow_chains_and_skip_unknown_files() -> None:
    imports = {"C.lean": ("B.lean",), "B.lean": ("A.lean", "Outside.lean"), "A.lean": ()}
    assert transitive_imports(imports) == {
        "C.lean": frozenset({"A.lean", "B.lean"}),
        "B.lean": frozenset({"A.lean"}),
        "A.lean": frozenset(),
    }
