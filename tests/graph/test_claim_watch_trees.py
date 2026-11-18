import dataclasses

import pytest
from graph_trees import GraphBuilder
from tactic_trees import AFTER_FIRST_HAVE, BARE_HAVE, CLAIM, ROOT

from lean_search.rl.claim_watch import Opening, TreeWatch, WatchKey, tree_watch
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search import TreeRecord

CONFIG = TrainingPhaseConfig()
UNPAID = dataclasses.replace(CONFIG, reward=dataclasses.replace(RewardConfig(), claims_earn_progress=False))
BAND = "1000-1499"
CLAIM_ON_GRAPH = WatchKey(Opening.BARE_OPEN_ON_GRAPH, True, BAND)
ERROR = WatchKey(Opening.OTHER, False, BAND)


def claim_and_error_tree() -> TreeRecord:
    """At the root: a bare claim the tree proves through its child, and a failing sample."""
    builder = GraphBuilder(ROOT)
    claimed = builder.child(builder.root, *CLAIM, text=BARE_HAVE, tactic_goals=(CLAIM,))
    after = builder.child(claimed, AFTER_FIRST_HAVE, text="linear_combination h₁ - h₀")
    builder.failure(builder.root, text="simp")
    return builder.record(builder.child(after, text="close"))


def watch(config: TrainingPhaseConfig = CONFIG) -> TreeWatch:
    return tree_watch(claim_and_error_tree(), config, BAND)


@pytest.mark.parametrize(("key", "count"), [(CLAIM_ON_GRAPH, 1), (ERROR, 1)], ids=["the claim", "the error"])
def test_the_roots_first_round_samples_are_counted_by_opening(key: WatchKey, count: int) -> None:
    assert watch().samples[key] == count


@pytest.mark.parametrize(
    ("config", "expected"), [(CONFIG, (1.05 + 0.15) / 2), (UNPAID, (0.85 + 0.15) / 2)], ids=["v1", "unpaid"]
)
def test_a_bare_claim_the_tree_proves_trains_with_its_score_minus_the_baseline(
    config: TrainingPhaseConfig, expected: float
) -> None:
    assert watch(config).advantages[CLAIM_ON_GRAPH].mean == pytest.approx(expected)


def test_a_share_is_of_every_first_round_policy_sample_in_the_tree() -> None:
    """The bare claim, one of four: the claim, the error, the claim's proof and the closer."""
    assert watch().share((Opening.BARE_OPEN_ON_GRAPH, Opening.BARE_CLOSED_IN_BLOCK)) == pytest.approx(0.25)


def test_watches_add_up_tree_by_tree() -> None:
    assert (watch() + watch()).advantages[ERROR].sequences == 2
