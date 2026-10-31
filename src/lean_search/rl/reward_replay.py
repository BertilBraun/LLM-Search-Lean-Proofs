"""The loop's trees labelled and scored again offline: the reward of 2026-10-31 against the rules phases 1-12 trained
with (48af4c8: no unproved claims or closed-form filler, unknown states untrained, explored off graph 0). Per tree the
tactic labels under both; the mean scores of bare claims, attempts at claims, `have … :=` blocks and real closers, old
against new over the same samples; the ordering checks as pairs of samples within a group; the samples, tactics and
groups whose advantage changes sign; and the drops (tactic advantages ≤ −1)."""

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
    # The first tactic made a claim its block leaves open after trying more (failed, or complete with further tactics):
    # one the tree never proves, and one it proves.
    INVENTED_ATTEMPT = "attempt at an invented claim"
    PROVABLE_ATTEMPT = "attempt at a provable claim"
    # Opening with `have … :=` (a claim with its proof).
    PROOF_HAVE = "have … :="
    # Reaching a proof.
    CLOSER = "closer"


CATEGORIES = tuple(Category)


@dataclass(frozen=True)
class Scores:
    """Multiplicity-weighted: the samples scored under both rules with both sums, and those scored under the new
    rules only with their sum."""

    samples: int = 0
    old_sum: float = 0.0
    new_sum: float = 0.0
    newly_scored: int = 0
    newly_scored_sum: float = 0.0

    @property
    def old_mean(self) -> float | None:
        return self.old_sum / self.samples if self.samples else None

    @property
    def new_mean(self) -> float | None:
        return self.new_sum / self.samples if self.samples else None

    @property
    def newly_scored_mean(self) -> float | None:
        return self.newly_scored_sum / self.newly_scored if self.newly_scored else None


@dataclass(frozen=True)
class SignChanges:
    """Multiplicity-weighted advantages known under both rules whose sign changed (zero counting as one), the flips
    from positive to negative and back, and the advantages known under the new rules only."""

    changed: int = 0
    to_negative: int = 0
    to_positive: int = 0
    newly_scored: int = 0


@dataclass(frozen=True)
class PairCounts:
    """Ordered pairs of samples of one group an ordering check compares, weighted by both multiplicities."""

    pairs: int = 0
    violations: int = 0


@dataclass(frozen=True)
class Drops:
    count: int = 0
    magnitude: float = 0.0
    # The summed |tactic advantage|.
    total_magnitude: float = 0.0


@dataclass(frozen=True)
class ReplaySample:
    """A group sample as the ordering checks see it, under one rule."""

    score: float | None
    multiplicity: int
    labels: tuple[TacticLabel, ...]
    complete: bool
    categories: frozenset[Category]


@dataclass(frozen=True)
class CategoryOrdering:
    """Every sample of `higher` scores above (with `strict` off: at least) every sample of `lower` in its group that
    is not in `higher` too."""

    higher: Category
    lower: Category
    strict: bool

    @property
    def text(self) -> str:
        return f"{self.higher} {'>' if self.strict else '≥'} {self.lower}"

    def holds(self, high: ReplaySample, low: ReplaySample) -> bool | None:
        """None when the pair is not compared."""
        if self.higher not in high.categories or self.lower not in low.categories or self.higher in low.categories:
            return None
        if high.score is None or low.score is None:
            return None
        return high.score > low.score if self.strict else high.score >= low.score - ZERO_ADVANTAGE


# A valid tactic that is no wasted step and makes no claim.
VALID_STEP_LABELS = (TacticLabel.PROOF_GRAPH, TacticLabel.OFF_GRAPH, TacticLabel.UNKNOWN)


@dataclass(frozen=True)
class ContinuationOrdering:
    """A complete block going on from where another block's error is, with the same labels before it, scores at least
    the error: from there on with valid steps only, or with any tactics after an open claim."""

    @property
    def text(self) -> str:
        return "valid continuation ≥ error there"

    def holds(self, valid: ReplaySample, failed: ReplaySample) -> bool | None:
        if not valid.complete or TacticLabel.FAILING not in failed.labels:
            return None
        position = failed.labels.index(TacticLabel.FAILING)
        if len(valid.labels) <= position or valid.labels[:position] != failed.labels[:position]:
            return None
        after_claim = TacticLabel.UNPROVED_CLAIM in failed.labels[:position]
        if not after_claim and any(label not in VALID_STEP_LABELS for label in valid.labels[position:]):
            return None
        if valid.score is None or failed.score is None:
            return None
        return valid.score >= failed.score - ZERO_ADVANTAGE


ORDERING_CHECKS: tuple[CategoryOrdering | ContinuationOrdering, ...] = (
    CategoryOrdering(Category.CLOSER, Category.PROOF_HAVE, strict=True),
    CategoryOrdering(Category.CLOSER, Category.INVENTED_ATTEMPT, strict=True),
    CategoryOrdering(Category.PROVABLE_ATTEMPT, Category.INVENTED_ATTEMPT, strict=False),
    CategoryOrdering(Category.INVENTED_ATTEMPT, Category.OPEN_BARE_CLAIM, strict=False),
    CategoryOrdering(Category.PROOF_HAVE, Category.OPEN_BARE_CLAIM, strict=False),
    ContinuationOrdering(),
)


def no_pairs() -> tuple[PairCounts, ...]:
    return tuple(PairCounts() for _ in ORDERING_CHECKS)


@dataclass(frozen=True)
class TreeReplay:
    trees: int = 0
    unreadable_trees: int = 0
    groups: int = 0
    # Groups with a sample or tactic whose advantage changed sign; groups trained under one rule only.
    groups_changed: int = 0
    groups_newly_trainable: int = 0
    groups_no_longer_trainable: int = 0
    # Multiplicity-weighted samples; the sign changes of their explanation advantages (score minus baseline) and of
    # their tactics' advantages.
    samples: int = 0
    sample_signs: SignChanges = field(default_factory=SignChanges)
    tactic_signs: SignChanges = field(default_factory=SignChanges)
    old_labels: TacticLabelCounts = field(default_factory=TacticLabelCounts)
    new_labels: TacticLabelCounts = field(default_factory=TacticLabelCounts)
    # Per `CATEGORIES`.
    category_scores: tuple[Scores, ...] = tuple(Scores() for _ in CATEGORIES)
    # Per `ORDERING_CHECKS`, under the new rules and the old.
    orderings: tuple[PairCounts, ...] = field(default_factory=no_pairs)
    old_orderings: tuple[PairCounts, ...] = field(default_factory=no_pairs)
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


def added_all(items: Sequence[Any], empty: Any) -> Any:
    result = empty
    for item in items:
        result = added(result, item)
    return result


def total(replays: Sequence[TreeReplay]) -> TreeReplay:
    return added_all(replays, TreeReplay())


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
        samples.append(dataclasses.replace(sample, tactics=old_judged_in_block(rewards, config)))
    return dataclasses.replace(group, samples=tuple(samples))


def categories(sample: GroupSample, outcomes: Sequence[TacticOutcome]) -> frozenset[Category]:
    """`outcomes`: the new labels."""
    found = set()
    first = outcomes[0]
    first_tactic = opening(sample.text)
    if is_bare_have(first_tactic):
        found.add(Category.BARE_HAVE)
        if first.label == TacticLabel.UNPROVED_CLAIM and sample.complete:
            found.add(Category.OPEN_BARE_CLAIM)
    if first.leaves_claim_open and (not sample.complete or len(outcomes) > 1):
        invented = first.label == TacticLabel.UNPROVED_CLAIM
        found.add(Category.INVENTED_ATTEMPT if invented else Category.PROVABLE_ATTEMPT)
    if is_proof_have(first_tactic):
        found.add(Category.PROOF_HAVE)
    if any(outcome.label == TacticLabel.PROOF_GRAPH and outcome.remaining_steps == 0 for outcome in outcomes):
        found.add(Category.CLOSER)
    return frozenset(found)


def sign(value: float | None) -> int | None:
    if value is None:
        return None
    return 0 if abs(value) <= ZERO_ADVANTAGE else (1 if value > 0 else -1)


def sign_changes(old: float | None, new: float | None, weight: int) -> SignChanges:
    old_sign, new_sign = sign(old), sign(new)
    return SignChanges(
        changed=weight * (old_sign is not None and new_sign is not None and old_sign != new_sign),
        to_negative=weight * (old_sign == 1 and new_sign == -1),
        to_positive=weight * (old_sign == -1 and new_sign == 1),
        newly_scored=weight * (old_sign is None and new_sign is not None),
    )


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


def category_scores(sample: GroupSample, old_sample: GroupSample, found: frozenset[Category]) -> tuple[Scores, ...]:
    weight = sample.multiplicity
    new_score, old_score = sample.score, old_sample.score
    assert new_score is not None
    scores = (
        Scores(newly_scored=weight, newly_scored_sum=weight * new_score)
        if old_score is None
        else Scores(weight, weight * old_score, weight * new_score)
    )
    return tuple(scores if category in found else Scores() for category in CATEGORIES)


def ordering_pairs(samples: Sequence[ReplaySample]) -> tuple[PairCounts, ...]:
    """Per `ORDERING_CHECKS`, over the ordered pairs of distinct samples of one group."""
    counts = []
    for check in ORDERING_CHECKS:
        pairs = violations = 0
        for first_index, first in enumerate(samples):
            for second_index, second in enumerate(samples):
                if first_index == second_index or (holds := check.holds(first, second)) is None:
                    continue
                weight = first.multiplicity * second.multiplicity
                pairs += weight
                violations += weight * (not holds)
        counts.append(PairCounts(pairs, violations))
    return tuple(counts)


def replay_samples(group: PolicyGroup, found: Sequence[frozenset[Category]]) -> list[ReplaySample]:
    return [
        ReplaySample(
            sample.score,
            sample.multiplicity,
            tuple(tactic.label for tactic in sample.tactics),
            sample.complete,
            sample_categories,
        )
        for sample, sample_categories in zip(group.samples, found, strict=True)
    ]


def group_replay(
    new_group: PolicyGroup,
    previous: PolicyGroup,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
) -> TreeReplay:
    """`new_group` and `previous`: the same samples under the new rules and the old."""
    new_advantages = group_advantages(new_group)
    old_advantages = group_advantages(previous)
    found = [
        categories(sample, tactics[labels.edges[sample.edge_ids[0]].executed_edge_id]) for sample in new_group.samples
    ]
    sample_signs = []
    tactic_signs = []
    scores = []
    for sample, old_sample, old, new, sample_categories in zip(
        new_group.samples, previous.samples, old_advantages.samples, new_advantages.samples, found, strict=True
    ):
        weight = sample.multiplicity
        sample_signs.append(sign_changes(old.sequence, new.sequence, weight))
        tactic_signs.extend(
            sign_changes(old_tactic, new_tactic, weight)
            for old_tactic, new_tactic in zip(old.tactics, new.tactics, strict=True)
        )
        scores.append(category_scores(sample, old_sample, sample_categories))
    old_trained = old_advantages.has_signal(CreditMode.PER_TACTIC)
    new_trained = new_advantages.has_signal(CreditMode.PER_TACTIC)
    summed_sample_signs = added_all(sample_signs, SignChanges())
    summed_tactic_signs = added_all(tactic_signs, SignChanges())
    return TreeReplay(
        groups=1,
        groups_changed=bool(summed_sample_signs.changed or summed_tactic_signs.changed),
        groups_newly_trainable=new_trained and not old_trained,
        groups_no_longer_trainable=old_trained and not new_trained,
        samples=new_group.sample_count,
        sample_signs=summed_sample_signs,
        tactic_signs=summed_tactic_signs,
        category_scores=added_all(scores, tuple(Scores() for _ in CATEGORIES)),
        orderings=ordering_pairs(replay_samples(new_group, found)),
        old_orderings=ordering_pairs(replay_samples(previous, found)),
        old_drops=drops([previous], [old_advantages]),
        new_drops=drops([new_group], [new_advantages]),
    )


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


def percent(part: float, whole: float) -> str:
    return f"{part / whole:.1%}" if whole else "-"


def signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.3f}"


def label_shares(counts: TacticLabelCounts) -> str:
    return ", ".join(f"{label} {percent(getattr(counts, label.value), counts.total)}" for label in TacticLabel)


def orderings_text(counts: Sequence[PairCounts]) -> str:
    return "; ".join(
        f"{check.text} {'-' if not found.pairs else 'FAILS' if found.violations else 'ok'} "
        f"({found.violations:,} of {found.pairs:,} pairs)"
        for check, found in zip(ORDERING_CHECKS, counts, strict=True)
    )


def signs_text(changes: SignChanges) -> str:
    return (
        f"{changes.changed:,} ({changes.to_negative:,} + to -, {changes.to_positive:,} - to +), "
        f"{changes.newly_scored:,} newly scored"
    )


def report(name: str, replay: TreeReplay) -> str:
    scores = "; ".join(
        f"{category} {signed(found.old_mean)} -> {signed(found.new_mean)} ({found.samples:,}), newly scored "
        f"{signed(found.newly_scored_mean)} ({found.newly_scored:,})"
        for category, found in zip(CATEGORIES, replay.category_scores, strict=True)
    )
    new, old = replay.new_drops, replay.old_drops
    return "\n".join(
        [
            f"{name}: {replay.trees:,} trees ({replay.unreadable_trees:,} unreadable), {replay.groups:,} groups, "
            f"{replay.samples:,} samples",
            f"  labels, new: {label_shares(replay.new_labels)}",
            f"  labels, old: {label_shares(replay.old_labels)}",
            f"  mean score old -> new over the samples both score (samples): {scores}",
            f"  ordering within groups, new rules: {orderings_text(replay.orderings)}",
            f"  ordering within groups, old rules: {orderings_text(replay.old_orderings)}",
            f"  sign changes: samples {signs_text(replay.sample_signs)}; tactics {signs_text(replay.tactic_signs)}; "
            f"groups {replay.groups_changed:,} with a change, {replay.groups_newly_trainable:,} newly trainable, "
            f"{replay.groups_no_longer_trainable:,} no longer",
            f"  drops (tactic advantage <= {DROP:g}): new {new.count:,} ({percent(new.magnitude, new.total_magnitude)} "
            f"of |tactic advantage|), old {old.count:,} ({percent(old.magnitude, old.total_magnitude)})",
        ]
    )
