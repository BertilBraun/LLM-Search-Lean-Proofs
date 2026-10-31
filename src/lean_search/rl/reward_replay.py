"""The loop's trees labelled and scored again offline: the reward of 2026-10-31 against the rules phases 1-12 trained
with (48af4c8: no unproved claims or closed-form filler, unknown states untrained, explored off graph 0). Per tree the
tactic labels under both, the mean scores of bare claims, failed attempts at a claim, `have … :=` blocks and real
closers, the samples and groups whose advantage changes sign, and the drops (tactic advantages ≤ −1)."""

import dataclasses
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from lean_search.lean.hypotheses import adds_only_redundant_hypotheses
from lean_search.rl.advantages import ZERO_ADVANTAGE, CreditMode, GroupAdvantages, group_advantages
from lean_search.rl.grpo_groups import (
    NO_GAIN,
    GroupSample,
    PolicyGroup,
    RewardConfig,
    RewardParts,
    TacticReward,
    policy_groups,
    reward_parts,
    tactic_reward,
)
from lean_search.rl.tree_summary import is_bare_have, is_proof_have, opening
from lean_search.search.graph_labels import GraphLabels, label_graph
from lean_search.search.records import TreeRecord, read_tree
from lean_search.search.tactic_labels import TacticGraph, TacticLabel, TacticLabelCounts, TacticOutcome, policy_tactics

# Tactic advantages at or below this are drops: about the whole reward of a proof-graph state lost.
DROP = -1.0


class Category(StrEnum):
    # Opening with a bare `have h : A`; of those, the blocks ending complete with the claim open.
    BARE_HAVE = "bare have"
    OPEN_BARE_CLAIM = "open bare claim"
    # The first tactic made a claim and the block failed before proving it.
    FAILED_ATTEMPT = "failed attempt"
    # Opening with `have … :=` (a claim with its proof).
    PROOF_HAVE = "have … :="
    # Reaching a proof.
    CLOSER = "closer"


CATEGORIES = tuple(Category)


@dataclass(frozen=True)
class Scores:
    """Multiplicity-weighted: the samples, those with an old score, and the scores' sums."""

    samples: int = 0
    old_scored: int = 0
    old_sum: float = 0.0
    new_sum: float = 0.0

    @property
    def old_mean(self) -> float | None:
        return self.old_sum / self.old_scored if self.old_scored else None

    @property
    def new_mean(self) -> float | None:
        return self.new_sum / self.samples if self.samples else None


@dataclass(frozen=True)
class Drops:
    count: int = 0
    magnitude: float = 0.0
    # The summed |tactic advantage|.
    total_magnitude: float = 0.0


@dataclass(frozen=True)
class TreeReplay:
    trees: int = 0
    unreadable_trees: int = 0
    groups: int = 0
    # Groups with a sample whose advantage changed sign (an advantage under both rules); groups trained under one
    # rule only.
    groups_changed: int = 0
    groups_newly_trainable: int = 0
    groups_no_longer_trainable: int = 0
    # Multiplicity-weighted samples, those with an advantage under the new rules only, those whose advantage changed
    # sign (zero counting as one), and of those the flips from positive to negative and back.
    samples: int = 0
    samples_newly_scored: int = 0
    samples_sign_changed: int = 0
    samples_to_negative: int = 0
    samples_to_positive: int = 0
    old_labels: TacticLabelCounts = field(default_factory=TacticLabelCounts)
    new_labels: TacticLabelCounts = field(default_factory=TacticLabelCounts)
    # Per `CATEGORIES`.
    category_scores: tuple[Scores, ...] = tuple(Scores() for _ in CATEGORIES)
    old_drops: Drops = field(default_factory=Drops)
    new_drops: Drops = field(default_factory=Drops)

    def scores(self, category: Category) -> Scores:
        return self.category_scores[CATEGORIES.index(category)]


def added(first: Any, second: Any) -> Any:
    """Two records of one dataclass summed field by field, nested dataclasses and tuples of them included."""
    if dataclasses.is_dataclass(first):
        return type(first)(
            **{
                item.name: added(getattr(first, item.name), getattr(second, item.name))
                for item in dataclasses.fields(first)
            }
        )
    if isinstance(first, tuple):
        return tuple(added(mine, theirs) for mine, theirs in zip(first, second, strict=True))
    return first + second


def total(replays: Sequence[TreeReplay]) -> TreeReplay:
    result = TreeReplay()
    for replay in replays:
        result = added(result, replay)
    return result


def evidence_label(graph: TacticGraph, outcome: TacticOutcome) -> TacticOutcome:
    label = TacticLabel.OFF_GRAPH if graph.is_off_graph_evidence(outcome.node_id) else TacticLabel.UNKNOWN
    return TacticOutcome(label, outcome.node_id)


def old_labels(
    record: TreeRecord, labels: GraphLabels, tactics: Mapping[int, Sequence[TacticOutcome]], min_expanded_nodes: int
) -> dict[int, tuple[TacticOutcome, ...]]:
    """Before 2026-10-31 an unproved claim and closed-form filler were off graph or unknown, by their evidence."""
    graph = TacticGraph(record, labels, min_expanded_nodes)
    relabelled = {}
    for edge_id, outcomes in tactics.items():
        edge = record.edges[edge_id]
        states = [record.nodes[edge.parent_id].goals, *edge.tactic_goals]
        judged = []
        for index, outcome in enumerate(outcomes):
            match outcome.label:
                case TacticLabel.UNPROVED_CLAIM:
                    judged.append(evidence_label(graph, outcome))
                case TacticLabel.REDUNDANT_HYPOTHESIS if index < len(edge.tactic_goals) and not any(
                    adds_only_redundant_hypotheses(state, states[index + 1]) for state in states[: index + 1]
                ):
                    judged.append(evidence_label(graph, outcome))
                case _:
                    judged.append(outcome)
        relabelled[edge_id] = tuple(judged)
    return relabelled


def old_tactic_reward(outcome: TacticOutcome, config: RewardConfig, node_steps: int) -> TacticReward:
    match outcome.label:
        case TacticLabel.UNKNOWN:
            return TacticReward(outcome.label, None)
        case TacticLabel.OFF_GRAPH:
            return TacticReward(outcome.label, reward_parts(0.0, 0.0, config))
        case _:
            return tactic_reward(outcome, config, node_steps)


def old_judged_in_block(rewards: Sequence[TacticReward], config: RewardConfig) -> tuple[TacticReward, ...]:
    reached = (TacticLabel.PROOF_GRAPH, TacticLabel.OFF_GRAPH)
    anchor = next((index for index, reward in enumerate(rewards) if reward.label in reached), 0)
    judged = []
    state: RewardParts | None = None
    for index, reward in enumerate(rewards):
        gain = None
        match reward.label:
            case TacticLabel.FAILING | TacticLabel.NO_PROGRESS | TacticLabel.REDUNDANT_HYPOTHESIS if index != anchor:
                gain = RewardParts(0.0, -config.wasted_tactic_cost)
            case TacticLabel.PROOF_GRAPH | TacticLabel.OFF_GRAPH:
                assert reward.parts is not None
                gain = None if state is None else reward.parts - state
                state = reward.parts
        judged.append(dataclasses.replace(reward, gain=gain))
    return tuple(judged)


def old_group(
    group: PolicyGroup, labels: GraphLabels, tactics: Mapping[int, Sequence[TacticOutcome]], config: RewardConfig
) -> PolicyGroup:
    """The group's samples with their old labels and scores (μ = 0, as in phases 1-12)."""
    node_steps = labels.remaining_steps[group.node_id]
    assert node_steps is not None
    samples = []
    for sample in group.samples:
        outcomes = tactics[labels.edges[sample.edge_ids[0]].executed_edge_id]
        rewards = [old_tactic_reward(outcome, config, node_steps) for outcome in outcomes]
        samples.append(dataclasses.replace(sample, tactics=old_judged_in_block(rewards, config), closing=NO_GAIN))
    return dataclasses.replace(group, samples=tuple(samples))


def categories(sample: GroupSample, outcomes: Sequence[TacticOutcome]) -> list[Category]:
    """`outcomes`: the new labels."""
    found = []
    first = outcomes[0]
    first_tactic = opening(sample.text)
    if is_bare_have(first_tactic):
        found.append(Category.BARE_HAVE)
        if first.label == TacticLabel.UNPROVED_CLAIM and sample.complete:
            found.append(Category.OPEN_BARE_CLAIM)
    if first.leaves_claim_open and not sample.complete:
        found.append(Category.FAILED_ATTEMPT)
    if is_proof_have(first_tactic):
        found.append(Category.PROOF_HAVE)
    if any(outcome.label == TacticLabel.PROOF_GRAPH and outcome.remaining_steps == 0 for outcome in outcomes):
        found.append(Category.CLOSER)
    return found


def sign(value: float | None) -> int | None:
    if value is None:
        return None
    return 0 if abs(value) <= ZERO_ADVANTAGE else (1 if value > 0 else -1)


def sign_changed(old: int | None, new: int | None) -> bool:
    return old is not None and new is not None and old != new


def drops(groups: Sequence[PolicyGroup], advantages: Sequence[GroupAdvantages]) -> Drops:
    values = [
        (value, sample.multiplicity)
        for group, group_advantage in zip(groups, advantages, strict=True)
        for sample, sample_advantages in zip(group.samples, group_advantage.samples, strict=True)
        for value in sample_advantages.tactics
        if value is not None
    ]
    dropped = [(value, weight) for value, weight in values if value <= DROP]
    return Drops(
        sum(weight for _, weight in dropped),
        sum(-value * weight for value, weight in dropped),
        sum(abs(value) * weight for value, weight in values),
    )


def sample_replay(
    sample: GroupSample,
    old_sample: GroupSample,
    old_sequence: float | None,
    new_sequence: float | None,
    outcomes: Sequence[TacticOutcome],
) -> TreeReplay:
    weight = sample.multiplicity
    old_sign, new_sign = sign(old_sequence), sign(new_sequence)
    old_score = old_sample.score
    assert sample.score is not None
    scores = Scores(weight, weight * (old_score is not None), weight * (old_score or 0.0), weight * sample.score)
    found = categories(sample, outcomes)
    return TreeReplay(
        samples=weight,
        samples_newly_scored=weight * (old_sign is None and new_sign is not None),
        samples_sign_changed=weight * sign_changed(old_sign, new_sign),
        samples_to_negative=weight * (old_sign == 1 and new_sign == -1),
        samples_to_positive=weight * (old_sign == -1 and new_sign == 1),
        category_scores=tuple(scores if category in found else Scores() for category in CATEGORIES),
    )


def group_replay(
    new_group: PolicyGroup,
    previous: PolicyGroup,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
) -> TreeReplay:
    new_advantages = group_advantages(new_group)
    old_advantages = group_advantages(previous)
    samples = [
        sample_replay(
            sample,
            old_sample,
            old_sample_advantages.sequence,
            new_sample_advantages.sequence,
            tactics[labels.edges[sample.edge_ids[0]].executed_edge_id],
        )
        for sample, old_sample, old_sample_advantages, new_sample_advantages in zip(
            new_group.samples, previous.samples, old_advantages.samples, new_advantages.samples, strict=True
        )
    ]
    changed = any(
        sign_changed(sign(old.sequence), sign(new.sequence))
        for old, new in zip(old_advantages.samples, new_advantages.samples, strict=True)
    )
    old_trained = old_advantages.has_signal(CreditMode.PER_TACTIC)
    new_trained = new_advantages.has_signal(CreditMode.PER_TACTIC)
    shape = TreeReplay(
        groups=1,
        groups_changed=changed,
        groups_newly_trainable=new_trained and not old_trained,
        groups_no_longer_trainable=old_trained and not new_trained,
        old_drops=drops([previous], [old_advantages]),
        new_drops=drops([new_group], [new_advantages]),
    )
    return total([shape, *samples])


def tree_replay(record: TreeRecord, config: RewardConfig) -> TreeReplay:
    labels = label_graph(record)
    minimum = config.off_graph_min_expanded_nodes
    tactics = policy_tactics(record, labels, minimum)
    before = old_labels(record, labels, tactics, minimum)
    groups = policy_groups(record, labels, tactics, [None] * len(record.nodes), config).groups
    labelled = TreeReplay(
        trees=1,
        old_labels=TacticLabelCounts.of(outcome.label for outcomes in before.values() for outcome in outcomes),
        new_labels=TacticLabelCounts.of(outcome.label for outcomes in tactics.values() for outcome in outcomes),
    )
    replays = [group_replay(group, old_group(group, labels, before, config), labels, tactics) for group in groups]
    return total([labelled, *replays])


def file_replay(path: Path, config: RewardConfig) -> TreeReplay:
    """An unreadable tree (truncated, corrupt) is counted and skipped."""
    try:
        record = read_tree(path, texts=False)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeReplay(trees=1, unreadable_trees=1)
    return tree_replay(record, config)


@dataclass(frozen=True)
class OrderingCheck:
    higher: Category
    lower: Category
    # Equal means suffice.
    strict: bool

    def holds(self, replay: TreeReplay) -> bool | None:
        high, low = replay.scores(self.higher).new_mean, replay.scores(self.lower).new_mean
        if high is None or low is None:
            return None
        return high > low if self.strict else high >= low - ZERO_ADVANTAGE

    @property
    def text(self) -> str:
        return f"{self.higher} {'>' if self.strict else '≥'} {self.lower}"


ORDERING_CHECKS = (
    OrderingCheck(Category.CLOSER, Category.PROOF_HAVE, strict=True),
    OrderingCheck(Category.CLOSER, Category.FAILED_ATTEMPT, strict=True),
    OrderingCheck(Category.FAILED_ATTEMPT, Category.OPEN_BARE_CLAIM, strict=False),
    OrderingCheck(Category.PROOF_HAVE, Category.BARE_HAVE, strict=True),
)


def percent(part: float, whole: float) -> str:
    return f"{part / whole:.1%}" if whole else "-"


def signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.3f}"


def label_shares(counts: TacticLabelCounts) -> str:
    return ", ".join(f"{label} {percent(getattr(counts, label.value), counts.total)}" for label in TacticLabel)


def check_text(check: OrderingCheck, replay: TreeReplay) -> str:
    holds = check.holds(replay)
    return f"{check.text} {'-' if holds is None else 'ok' if holds else 'FAILS'}"


def report(name: str, replay: TreeReplay) -> str:
    scores = "; ".join(
        f"{category} {signed(found.old_mean)} -> {signed(found.new_mean)} ({found.samples:,})"
        for category, found in zip(CATEGORIES, replay.category_scores, strict=True)
    )
    new, old = replay.new_drops, replay.old_drops
    return "\n".join(
        [
            f"{name}: {replay.trees:,} trees ({replay.unreadable_trees:,} unreadable), {replay.groups:,} groups, "
            f"{replay.samples:,} samples",
            f"  labels, new: {label_shares(replay.new_labels)}",
            f"  labels, old: {label_shares(replay.old_labels)}",
            f"  mean score old -> new (samples): {scores}",
            f"  ordering, new rules: {', '.join(check_text(check, replay) for check in ORDERING_CHECKS)}",
            f"  sign changes: samples {replay.samples_sign_changed:,} ({replay.samples_to_negative:,} + to -, "
            f"{replay.samples_to_positive:,} - to +), {replay.samples_newly_scored:,} newly scored; groups "
            f"{replay.groups_changed:,} with a change, "
            f"{replay.groups_newly_trainable:,} newly trainable, {replay.groups_no_longer_trainable:,} no longer",
            f"  drops (tactic advantage <= {DROP:g}): new {new.count:,} ({percent(new.magnitude, new.total_magnitude)} "
            f"of |tactic advantage|), old {old.count:,} ({percent(old.magnitude, old.total_magnitude)})",
        ]
    )
