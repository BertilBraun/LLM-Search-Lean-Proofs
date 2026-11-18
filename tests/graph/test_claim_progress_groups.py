import dataclasses

import pytest
from graph_trees import GraphBuilder
from tactic_trees import AFTER_FIRST_HAVE, BARE_HAVE, CLAIM, ROOT, claim_tree, with_pieces

from lean_search.rl.grpo_groups import GroupSample, RewardConfig, policy_groups
from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.search.tactic_labels import policy_tactics

DEFAULT = RewardConfig()
UNPAID = dataclasses.replace(DEFAULT, claims_earn_progress=False)
INLINE = "have h₂ : x = -4 := by\n  linear_combination h₁ - h₀"
INLINE_PIECES = ["have h₂ : x = -4", "linear_combination h₁ - h₀"]
ON_GRAPH = 0.85
STEP = 0.2
# The local share times the bonus of the goal the claim's proof closes.
CLOSED_GOAL = 0.15 * 0.1


def root_sample(record: TreeRecord, text: str, config: RewardConfig) -> GroupSample:
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, config.off_graph_min_expanded_nodes)
    root = next(group for group in policy_groups(record, labels, tactics, [None] * len(record.nodes), config).groups)
    assert root.node_id == 0
    (sample,) = [sample for sample in root.samples if sample.text == text]
    return sample


def inline_tree() -> TreeRecord:
    """The root, the flattened inline proof of `x = -4` and a closer of the rest, beside a bare claim the tree proves
    through its own child and the same closer."""
    builder = GraphBuilder(ROOT)
    proved = builder.child(
        builder.root, AFTER_FIRST_HAVE, text=INLINE, tactics=2, tactic_goals=(CLAIM, (AFTER_FIRST_HAVE,))
    )
    builder.tree.mark_proof_path(builder.child(proved, text="close"))
    claimed = builder.child(builder.root, *CLAIM, text=BARE_HAVE, tactic_goals=(CLAIM,))
    after = builder.child(claimed, AFTER_FIRST_HAVE, text="linear_combination h₁ - h₀")
    record = builder.record(builder.child(after, text="close"))
    return with_pieces(record, {INLINE: INLINE_PIECES})


@pytest.mark.parametrize(("config", "expected"), [(DEFAULT, ON_GRAPH + STEP), (UNPAID, ON_GRAPH)], ids=["v1", "unpaid"])
def test_a_bare_claim_the_tree_proves_scores_its_step_only_while_claims_earn_progress(
    config: RewardConfig, expected: float
) -> None:
    assert root_sample(claim_tree(on_proof_graph=True), BARE_HAVE, config).score == pytest.approx(expected)


@pytest.mark.parametrize("config", [DEFAULT, UNPAID], ids=["v1", "unpaid"])
def test_an_inline_proof_of_a_claim_beats_the_bare_claim_by_its_proofs_step(config: RewardConfig) -> None:
    inline = root_sample(inline_tree(), INLINE, config).score
    bare = root_sample(inline_tree(), BARE_HAVE, config).score
    assert inline is not None and bare is not None and inline - bare == pytest.approx(STEP + CLOSED_GOAL)


def test_an_inline_proof_of_a_claim_earns_only_its_proofs_step_without_claim_progress() -> None:
    assert root_sample(inline_tree(), INLINE, UNPAID).score == pytest.approx(ON_GRAPH + STEP + CLOSED_GOAL)


def test_the_flattened_claim_of_an_inline_proof_is_a_claim() -> None:
    assert root_sample(inline_tree(), INLINE, UNPAID).tactics[0].adds_claim
