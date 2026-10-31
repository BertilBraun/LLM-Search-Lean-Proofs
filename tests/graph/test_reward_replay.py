from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from rl_samples import sample
from tactic_trees import BARE_HAVE, CLAIM, CONTEXT, ROOT, TARGET, claim_tree, example_tree

from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.reward_replay import (
    Category,
    Scores,
    TreeReplay,
    added,
    file_replay,
    old_labels,
    report,
    sample_replay,
    tree_replay,
)
from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import write_tree
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome, policy_tactics

CONFIG = RewardConfig()
FILLER = f"{CONTEXT}\nh₂ : 0 < (1:ℝ)\n{TARGET}"
INLINE_ATTEMPT = "have h₂ : x = -4 := by\n  nlinarith"


def first_old_label(record: TreeRecord, text: str) -> TacticLabel:
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, CONFIG.off_graph_min_expanded_nodes)
    (edge,) = [edge for edge in record.edges if edge.text == text]
    return old_labels(record, labels, tactics, CONFIG.off_graph_min_expanded_nodes)[edge.edge_id][0].label


def test_an_unproved_claim_was_unknown_before() -> None:
    assert first_old_label(claim_tree(), BARE_HAVE) == TacticLabel.UNKNOWN


def test_closed_form_filler_was_unknown_before() -> None:
    builder = GraphBuilder(ROOT)
    builder.child(builder.root, FILLER, text="have", tactic_goals=((FILLER,),))
    assert first_old_label(builder.record(builder.child(builder.root, text="close")), "have") == TacticLabel.UNKNOWN


def attempt_tree() -> TreeRecord:
    builder = GraphBuilder(ROOT)
    claim = builder.child(builder.root, *CLAIM, text=INLINE_ATTEMPT, failure_after=1, tactic_goals=(CLAIM,))
    builder.duplicate(builder.root, claim, text=BARE_HAVE, tactic_goals=(CLAIM,))
    return builder.record(builder.child(builder.root, text="close"))


def test_a_bare_claim_unscored_before_is_newly_scored() -> None:
    assert tree_replay(claim_tree(), CONFIG).samples_newly_scored == 1


def test_the_samples_of_every_group_are_counted() -> None:
    assert tree_replay(attempt_tree(), CONFIG).samples == 3


@pytest.mark.parametrize(
    ("category", "score"),
    [
        (Category.OPEN_BARE_CLAIM, -0.25),
        (Category.FAILED_ATTEMPT, -0.15),
        (Category.CLOSER, 0.85 + 0.2 + 0.15 * 0.1),
    ],
)
def test_the_new_mean_score_of_each_category(category: Category, score: float) -> None:
    assert tree_replay(attempt_tree(), CONFIG).scores(category).new_mean == pytest.approx(score)


def test_the_old_mean_score_leaves_out_samples_without_an_old_score() -> None:
    assert tree_replay(attempt_tree(), CONFIG).scores(Category.OPEN_BARE_CLAIM).old_mean is None


def test_the_ordering_checks_hold_on_the_example() -> None:
    assert "FAILS" not in report("example", tree_replay(example_tree(), CONFIG))


def test_tree_replays_add_up_field_by_field() -> None:
    first = TreeReplay(trees=1, category_scores=tuple(Scores(samples=1) for _ in Category))
    assert added(first, first).scores(Category.CLOSER).samples == 2


def test_an_unreadable_tree_is_counted(tmp_path: Path) -> None:
    path = tmp_path / "broken.json.gz"
    path.write_bytes(b"truncated")
    assert file_replay(path, CONFIG).unreadable_trees == 1


def test_a_tree_file_replays_like_its_record(tmp_path: Path) -> None:
    write_tree(tmp_path / "tree.json.gz", example_tree())
    assert file_replay(tmp_path / "tree.json.gz", CONFIG) == tree_replay(example_tree(), CONFIG)


def flipped(old_sequence: float, new_sequence: float) -> TreeReplay:
    stopped = sample("s", TacticLabel.PROOF_GRAPH, multiplicity=2)
    return sample_replay(stopped, stopped, old_sequence, new_sequence, [TacticOutcome(TacticLabel.PROOF_GRAPH)])


def test_a_sample_flipping_to_positive_is_counted_with_its_multiplicity() -> None:
    assert flipped(-0.1, 0.3).samples_to_positive == 2


def test_a_sample_flipping_to_negative_is_counted_as_a_sign_change() -> None:
    assert flipped(0.1, -0.3).samples_sign_changed == 2


def test_a_sample_keeping_its_sign_is_no_sign_change() -> None:
    assert flipped(0.1, 0.3).samples_sign_changed == 0
