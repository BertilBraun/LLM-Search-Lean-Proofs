import dataclasses

import pytest
from graph_trees import GraphBuilder
from tactic_trees import (
    BARE_HAVE,
    CLAIM,
    CONSTRUCTOR,
    CONTEXT,
    COPY,
    ERRORING_HAVE,
    FIRST_THEN_FAILING,
    OPEN_ENDED_HAVE,
    PROOF,
    PROVABLE_ATTEMPT,
    ROOT,
    claim_tree,
    example_tree,
    open_claims_tree,
)

from lean_search.rl.advantages import CreditMode, SampleAdvantages, group_advantages
from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardConfig, TreeGroups, policy_groups
from lean_search.search import FailureKind, StepSource, TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.search.tactic_labels import TacticLabel, policy_tactics
from lean_search.value.graph_targets import RemainingStepsReadout, recorded_estimates

READOUT = RemainingStepsReadout()
CONFIG = RewardConfig()
SINGLE_EXPANSION_EVIDENCE = dataclasses.replace(CONFIG, off_graph_min_expanded_nodes=1)


def tree_groups(record: TreeRecord, config: RewardConfig = CONFIG) -> TreeGroups:
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, config.off_graph_min_expanded_nodes)
    return policy_groups(record, labels, tactics, recorded_estimates(record, READOUT), config)


def groups(record: TreeRecord, config: RewardConfig = CONFIG) -> list[PolicyGroup]:
    return list(tree_groups(record, config).groups)


def root_sample(text: str, config: RewardConfig = CONFIG) -> GroupSample:
    (root,) = groups(example_tree(), config)
    (match,) = [sample for sample in root.samples if sample.text == text]
    return match


def tactic_rewards(text: str, config: RewardConfig = CONFIG) -> list[float | None]:
    return [None if tactic.parts is None else tactic.parts.total for tactic in root_sample(text, config).tactics]


def test_only_the_expanded_proof_graph_node_has_a_group() -> None:
    assert [group.node_id for group in groups(example_tree())] == [0]


def test_unsolved_tree_has_no_groups() -> None:
    builder = GraphBuilder("⊢ p")
    child = builder.child(builder.root, "⊢ q")
    builder.failure(child)
    assert groups(builder.record()) == []


def test_proof_tactics_earn_their_progress_and_the_closing_bonus() -> None:
    assert tactic_rewards(PROOF) == pytest.approx([0.85 + 0.2, 0.85 + 0.4, 0.85 + 0.6 + 0.15 * 0.1])


def test_failing_tactic_after_a_proof_graph_tactic() -> None:
    assert tactic_rewards(FIRST_THEN_FAILING) == pytest.approx([0.85 + 0.2, -0.15, None])


def test_tactics_after_the_first_are_judged_within_the_block() -> None:
    gains = [None if tactic.gain is None else tactic.gain.total for tactic in root_sample(PROOF).tactics]
    assert gains == pytest.approx([None, 0.2, 0.2 + 0.15 * 0.1])


def test_failing_tactic_after_the_first_costs_its_tokens() -> None:
    gains = [None if tactic.gain is None else tactic.gain.total for tactic in root_sample(FIRST_THEN_FAILING).tactics]
    assert gains == pytest.approx([None, -0.1, None])


def test_redundant_hypothesis_scores_as_a_failure() -> None:
    assert tactic_rewards(COPY) == pytest.approx([-0.15])


def test_goal_split_into_a_dead_end_scores_like_an_unknown_state() -> None:
    assert tactic_rewards(CONSTRUCTOR) == pytest.approx([-0.5 * 0.15])


def test_dead_end_scores_like_an_unknown_state_before_the_gate() -> None:
    builder = GraphBuilder("⊢ p")
    dead_end = builder.child(builder.root, "⊢ q", text="detour")
    builder.failure(dead_end)
    (root,) = groups(builder.record(builder.child(builder.root, text="close")))
    (detour,) = [sample for sample in root.samples if sample.text == "detour"]
    assert detour.score == pytest.approx(-0.5 * 0.15)


def test_explored_off_graph_state_scores_like_an_unknown_state_before_the_gate() -> None:
    builder = GraphBuilder("⊢ p")
    node = builder.child(builder.root, "⊢ q 0", text="detour")
    for index in range(1, CONFIG.off_graph_min_expanded_nodes + 1):
        node = builder.child(node, f"⊢ q {index}")
    (root,) = groups(builder.record(builder.child(builder.root, text="close")))
    (detour,) = [sample for sample in root.samples if sample.text == "detour"]
    assert detour.score == pytest.approx(-0.5 * 0.15)


def test_off_graph_state_with_live_children_and_too_few_expanded_nodes_scores_as_unknown() -> None:
    builder = GraphBuilder("⊢ p")
    off_graph = builder.child(builder.root, "⊢ q", text="detour")
    builder.child(off_graph, "⊢ r")
    proof = builder.child(builder.root, text="close")
    (root,) = groups(builder.record(proof))
    (detour,) = [sample for sample in root.samples if sample.text == "detour"]
    assert detour.score == pytest.approx(-0.5 * 0.15)


def claim_sample(on_proof_graph: bool = False) -> GroupSample:
    (root,) = [group for group in groups(claim_tree(on_proof_graph=on_proof_graph)) if group.node_id == 0]
    (claim,) = [sample for sample in root.samples if sample.text == BARE_HAVE]
    return claim


def test_bare_claim_left_open_scores_a_failure_and_c() -> None:
    assert claim_sample().score == pytest.approx(-0.15 - 0.1)


INLINE_ATTEMPT = "have h₂ : x = -4 := by\n  nlinarith"


def attempt_tree() -> TreeRecord:
    """A bare `have` and a flattened `have … := by nlinarith` whose nlinarith fails, both at the claim's node."""
    builder = GraphBuilder(ROOT)
    claim = builder.child(builder.root, *CLAIM, text=INLINE_ATTEMPT, failure_after=1, tactic_goals=(CLAIM,))
    builder.duplicate(builder.root, claim, text=BARE_HAVE, tactic_goals=(CLAIM,))
    return builder.record(builder.child(builder.root, text="close"))


def attempt_samples() -> dict[str, GroupSample]:
    (root,) = groups(attempt_tree())
    return {sample.text: sample for sample in root.samples}


def test_failed_inline_proof_of_an_invented_claim_scores_like_the_bare_claim() -> None:
    samples = attempt_samples()
    assert samples[INLINE_ATTEMPT].score == pytest.approx(samples[BARE_HAVE].score)


def test_failed_inline_proof_charges_its_claim_not_its_failing_tactic() -> None:
    gains = [None if tactic.gain is None else tactic.gain.total for tactic in attempt_samples()[INLINE_ATTEMPT].tactics]
    assert gains[:2] == [None, 0.0]


def open_claims_samples() -> dict[str, tuple[GroupSample, SampleAdvantages]]:
    (root,) = [group for group in groups(open_claims_tree()) if group.node_id == 0]
    advantages = group_advantages(root)
    return {sample.text: (sample, found) for sample, found in zip(root.samples, advantages.samples, strict=True)}


def test_failed_attempt_at_a_provable_claim_scores_above_one_at_an_invented_claim() -> None:
    samples = open_claims_samples()
    assert samples[PROVABLE_ATTEMPT][0].score > samples[ERRORING_HAVE][0].score


def test_an_invented_claims_opener_gets_a_lower_advantage_than_a_provable_ones() -> None:
    samples = open_claims_samples()
    assert samples[ERRORING_HAVE][1].tactics[0] < samples[PROVABLE_ATTEMPT][1].tactics[0]


def test_failing_proof_tactic_after_an_invented_claim_gets_no_advantage() -> None:
    assert open_claims_samples()[ERRORING_HAVE][1].tactics[1] == 0.0


def test_flattened_have_left_open_by_a_valid_tactic_scores_like_the_erroring_one() -> None:
    samples = open_claims_samples()
    assert samples[OPEN_ENDED_HAVE][0].score == pytest.approx(samples[ERRORING_HAVE][0].score)


def test_unproved_suffices_scores_like_a_bare_claim() -> None:
    builder = GraphBuilder(ROOT)
    suffices = "suffices h₂ : x = -4 by linear_combination h₀ - h₂"
    builder.child(builder.root, f"{CONTEXT}\n⊢ x = -4", text=suffices, tactic_goals=((f"{CONTEXT}\n⊢ x = -4",),))
    builder.child(builder.root, *CLAIM, text=BARE_HAVE, tactic_goals=(CLAIM,))
    (root,) = groups(builder.record(builder.child(builder.root, text="close")))
    scores = {sample.text: sample.score for sample in root.samples}
    assert scores[suffices] == pytest.approx(scores[BARE_HAVE])


def test_claim_on_the_proof_graph_keeps_its_label() -> None:
    assert claim_sample(on_proof_graph=True).tactics[0].label == TacticLabel.PROOF_GRAPH


def test_expanded_off_graph_state_earns_its_value_part_after_the_gate() -> None:
    builder = GraphBuilder("⊢ p")
    off_graph = builder.child(builder.root, "⊢ q", value=4.0, text="detour")
    builder.child(off_graph, "⊢ r")
    proof = builder.child(builder.root, text="close")
    labels = label_graph(record := builder.record(proof))
    config = dataclasses.replace(SINGLE_EXPANSION_EVIDENCE, value_share=0.15)
    tactics = policy_tactics(record, labels, config.off_graph_min_expanded_nodes)
    (root,) = policy_groups(record, labels, tactics, recorded_estimates(record, READOUT), config).groups
    (detour,) = [sample for sample in root.samples if sample.text == "detour"]
    expected = 0.85 * 0.15 * READOUT.estimate(4.0).proof_probability + 0.15 * -0.5
    assert detour.tactics[0].parts is not None and detour.tactics[0].parts.total == pytest.approx(expected)


def test_identical_texts_merge_and_keep_their_multiplicity() -> None:
    builder = GraphBuilder("⊢ p")
    twice = builder.failure(builder.root, text="twice", sample_count=2)
    builder.repeat(builder.root, twice)
    proof = builder.child(builder.root, text="close")
    (root,) = groups(builder.record(proof))
    assert [(sample.text, sample.multiplicity) for sample in root.samples] == [("twice", 3), ("close", 1)]


def test_unparsed_samples_merge_into_one_failing_sample() -> None:
    builder = GraphBuilder("⊢ p")
    builder.unparsed(builder.root)
    builder.unparsed(builder.root)
    proof = builder.child(builder.root, text="close")
    (root,) = groups(builder.record(proof))
    assert (root.samples[0].multiplicity, root.samples[0].score) == (2, pytest.approx(-0.15))


def test_group_holds_only_policy_samples_without_infrastructure_failures() -> None:
    builder = GraphBuilder("⊢ p")
    builder.failure(builder.root, text="omega", source=StepSource.AUTOMATION)
    builder.failure(builder.root, FailureKind.REPL_FAILURE, text="crashed")
    proof = builder.child(builder.root, text="close")
    (root,) = groups(builder.record(proof))
    assert [sample.text for sample in root.samples] == ["close"]


def sweep_proof_tree() -> TreeRecord:
    """The sweep proves the root; the policy's samples fail or reach a never-expanded state."""
    builder = GraphBuilder("⊢ p")
    builder.failure(builder.root, text="linarith")
    builder.child(builder.root, "⊢ q", text="detour")
    proof = builder.child(builder.root, text="omega", source=StepSource.AUTOMATION)
    return builder.record(proof)


def test_group_without_a_policy_proof_is_left_out() -> None:
    assert tree_groups(sweep_proof_tree()) == TreeGroups(groups=(), without_policy_proof=1)


def test_unknown_and_failing_samples_alone_carry_a_signal() -> None:
    config = dataclasses.replace(CONFIG, require_policy_proof=False)
    (root,) = groups(sweep_proof_tree(), config)
    assert group_advantages(root).has_signal(CreditMode.PER_TACTIC)


def test_group_without_a_policy_proof_stays_when_not_required() -> None:
    config = dataclasses.replace(CONFIG, require_policy_proof=False)
    assert [group.node_id for group in groups(sweep_proof_tree(), config)] == [0]


def test_policy_sample_repeating_the_sweep_proof_counts_as_a_policy_proof() -> None:
    builder = GraphBuilder("⊢ p")
    builder.failure(builder.root, text="linarith")
    proof = builder.child(builder.root, text="omega", source=StepSource.AUTOMATION)
    builder.repeat(builder.root, builder.tree.edges[proof.edge_id])
    assert [group.node_id for group in groups(builder.record(proof))] == [0]
