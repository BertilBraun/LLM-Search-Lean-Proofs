import dataclasses
from collections.abc import Sequence
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tactic_trees import BARE_HAVE, CLAIM, CONTEXT, ROOT, TARGET, claim_tree, example_tree, open_claims_tree

from lean_search.rl.grpo_groups import (
    EVIDENCE_LABELS,
    NO_GAIN,
    REACHED_STATE_LABELS,
    PolicyGroup,
    RewardConfig,
    RewardParts,
    TacticReward,
    policy_groups,
    tactic_reward,
)
from lean_search.rl.reward_replay import (
    ORDERING_CHECKS,
    Category,
    ContinuationOrdering,
    PairCounts,
    Scores,
    TreeReplay,
    added,
    file_replay,
    group_replay,
    old_group,
    old_labels,
    report,
    sign_changes,
    total,
    tree_replay,
)
from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import write_tree
from lean_search.search.tactic_labels import TacticLabel, policy_tactics

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
    assert tree_replay(claim_tree(), CONFIG).sample_signs.newly_scored == 1


def test_the_samples_of_every_group_are_counted() -> None:
    assert tree_replay(attempt_tree(), CONFIG).samples == 3


@pytest.mark.parametrize(
    ("category", "score"),
    [(Category.OPEN_BARE_CLAIM, -0.25), (Category.INVENTED_ATTEMPT, -0.25)],
)
def test_the_mean_score_of_the_newly_scored_samples_of_each_category(category: Category, score: float) -> None:
    assert tree_replay(attempt_tree(), CONFIG).scores(category).newly_scored_mean == pytest.approx(score)


def test_a_sample_scored_under_both_rules_enters_both_means() -> None:
    closers = tree_replay(attempt_tree(), CONFIG).scores(Category.CLOSER)
    assert (closers.old_mean, closers.new_mean) == pytest.approx((0.85 + 0.2 + 0.015, 0.85 + 0.2 + 0.015))


def test_a_sample_without_an_old_score_is_left_out_of_both_means() -> None:
    assert tree_replay(attempt_tree(), CONFIG).scores(Category.OPEN_BARE_CLAIM).samples == 0


def test_tactic_advantages_changing_sign_are_counted() -> None:
    assert tree_replay(attempt_tree(), CONFIG).tactic_signs.changed == 2


def test_a_flip_to_negative_is_counted_with_its_multiplicity() -> None:
    assert sign_changes(0.1, -0.3, 2).to_negative == 2


def test_a_flip_to_positive_is_counted_as_a_sign_change() -> None:
    assert sign_changes(-0.1, 0.3, 2).changed == 2


def test_keeping_the_sign_is_no_sign_change() -> None:
    assert sign_changes(0.1, 0.3, 2).changed == 0


def test_an_advantage_known_under_the_new_rules_only_is_newly_scored() -> None:
    assert sign_changes(None, 0.3, 1).newly_scored == 1


def test_the_ordering_checks_hold_on_the_example() -> None:
    assert "FAILS" not in report("example", tree_replay(example_tree(), CONFIG))


def test_the_ordering_checks_hold_on_review_us_claims() -> None:
    assert not any(found.violations for found in tree_replay(open_claims_tree(), CONFIG).orderings)


def test_the_ordering_checks_compare_review_us_claims() -> None:
    assert all(found.pairs for found in tree_replay(open_claims_tree(), CONFIG).orderings[2:])


def judged_by_8e99fc9(rewards: Sequence[TacticReward], config: RewardConfig) -> tuple[TacticReward, ...]:
    """The rule review U found findings 1 and 2 in; its closing cost on a block stopping on an open claim is folded
    into the block's last gain (the anchor's R without one), which leaves the score as it was."""
    cost = RewardParts(0.0, -config.wasted_tactic_cost)
    labels = [reward.label for reward in rewards]
    claim = labels.index(TacticLabel.UNPROVED_CLAIM) if TacticLabel.UNPROVED_CLAIM in labels else None
    failure = labels.index(TacticLabel.FAILING) if TacticLabel.FAILING in labels else None
    attempt = range(claim, failure) if claim is not None and failure is not None else range(0)
    reached = [index for index, label in enumerate(labels) if label in REACHED_STATE_LABELS and index not in attempt]
    anchor = min(reached + ([failure] if attempt and failure is not None else []), default=0)
    reference: RewardParts | None = None
    evidence = False
    judged = []
    for index, reward in enumerate(rewards):
        gain = None
        after_claim = claim is not None and index > claim
        match reward.label:
            case _ if index in attempt:
                gain = NO_GAIN
            case TacticLabel.PROOF_GRAPH | TacticLabel.OFF_GRAPH | TacticLabel.UNKNOWN if after_claim:
                gain = NO_GAIN
            case TacticLabel.MASKED:
                pass
            case label if index == anchor:
                if label in REACHED_STATE_LABELS:
                    reference, evidence = reward.parts, label in EVIDENCE_LABELS
            case (
                TacticLabel.FAILING
                | TacticLabel.NO_PROGRESS
                | TacticLabel.REDUNDANT_HYPOTHESIS
                | TacticLabel.UNPROVED_CLAIM
            ):
                gain = cost
            case TacticLabel.UNKNOWN if evidence:
                gain = NO_GAIN if index < reached[-1] else cost
            case TacticLabel.PROOF_GRAPH | TacticLabel.OFF_GRAPH | TacticLabel.UNKNOWN:
                assert reward.parts is not None and reference is not None
                gain = reward.parts - reference
                reference, evidence = reward.parts, reward.label in EVIDENCE_LABELS
        judged.append(dataclasses.replace(reward, gain=gain))
    if claim is not None and failure is None:
        last = max(index for index, reward in enumerate(judged) if reward.gain is not None or index == anchor)
        closed = judged[last]
        if closed.gain is None:
            assert closed.parts is not None
            judged[last] = dataclasses.replace(closed, parts=closed.parts + cost)
        else:
            judged[last] = dataclasses.replace(closed, gain=closed.gain + cost)
    return tuple(judged)


def replay_under_8e99fc9(record: TreeRecord) -> TreeReplay:
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, CONFIG.off_graph_min_expanded_nodes)
    before = old_labels(record, labels, tactics, CONFIG.off_graph_min_expanded_nodes)
    replays = []
    for group in policy_groups(record, labels, tactics, [None] * len(record.nodes), CONFIG).groups:
        node_steps = labels.remaining_steps[group.node_id]
        assert node_steps is not None
        samples = []
        for sample in group.samples:
            outcomes = tactics[labels.edges[sample.edge_ids[0]].executed_edge_id]
            rewards = [tactic_reward(outcome, CONFIG, node_steps) for outcome in outcomes]
            samples.append(dataclasses.replace(sample, tactics=judged_by_8e99fc9(rewards, CONFIG)))
        rejudged = PolicyGroup(group.problem_name, group.node_id, group.goals, tuple(samples), group.feedback)
        replays.append(group_replay(rejudged, old_group(group, labels, before, CONFIG), labels, tactics))
    return total(replays)


def new_rules_line(replay: TreeReplay) -> str:
    (line,) = [line for line in report("tree", replay).splitlines() if "new rules" in line]
    return line


def test_review_us_claims_under_the_rule_they_were_found_in_print_a_failed_check() -> None:
    assert "FAILS" in new_rules_line(replay_under_8e99fc9(open_claims_tree()))


@pytest.mark.parametrize(
    "check",
    [
        next(check for check in ORDERING_CHECKS if check.text.startswith(Category.PROVABLE_ATTEMPT)),
        next(check for check in ORDERING_CHECKS if isinstance(check, ContinuationOrdering)),
    ],
    ids=["finding 1", "finding 2"],
)
def test_each_finding_of_review_u_fails_its_check_under_the_rule_it_was_found_in(check: object) -> None:
    replay = replay_under_8e99fc9(open_claims_tree())
    assert replay.orderings[ORDERING_CHECKS.index(check)].violations > 0


def test_tree_replays_add_up_field_by_field() -> None:
    first = TreeReplay(trees=1, category_scores=tuple(Scores(samples=1) for _ in Category))
    assert added(first, first).scores(Category.CLOSER).samples == 2


def test_pair_counts_add_up_per_check() -> None:
    first = TreeReplay(orderings=tuple(PairCounts(1, 1) for _ in ORDERING_CHECKS))
    assert added(first, first).orderings[0] == PairCounts(2, 2)


def test_an_unreadable_tree_is_counted(tmp_path: Path) -> None:
    path = tmp_path / "broken.json.gz"
    path.write_bytes(b"truncated")
    assert file_replay(path, CONFIG).unreadable_trees == 1


def test_a_tree_file_replays_like_its_record(tmp_path: Path) -> None:
    write_tree(tmp_path / "tree.json.gz", example_tree())
    assert file_replay(tmp_path / "tree.json.gz", CONFIG) == tree_replay(example_tree(), CONFIG)
