"""Where per-tactic GRPO puts its advantage on blocks that reach the proof graph and then run a failing tactic, on a
loop's recorded trees, under the phase's own reward and under reward variants, compared on the same groups (the
trainer's groups as `bare_have_credit.variant_groups` builds them; sequence and per-tactic advantages, no tokens).

    PYTHONPATH=src:experiments/analysis python experiments/analysis/continuation_credit.py \
        --run /workspace/runs/followup_A --phases 1 2 3 4 \
        --variants '{"c 0.3": {"wasted_tactic_cost": 0.3}, "never positive": {"transform": "fail_never_positive"}}' \
        --output continuation.json

A variant is `[reward]` overrides plus, optionally, `transform` (`Transform`) and `masked_cost` (what each tactic after
the block's first failing one costs, charged to the failing one). A sample is complete on the graph (it reaches the
proof graph, `GroupSample.reaches_proof_graph`, without a failing tactic), fails after the graph (it reaches it, then a
failing tactic), or never on the graph. Continuation tactics are those after the block's first proof-graph tactic:
their summed advantage is what the trainer pays for going on after progress, split by how they ended. The sequence
advantage is what per-tactic credit puts on the explanation tokens.
"""

import argparse
import contextlib
import dataclasses
import json
import tomllib
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from multiprocessing.pool import Pool
from pathlib import Path
from typing import NamedTuple

from bare_have_credit import BASE_VARIANT, Variant, sampled_entries, variant_groups

from lean_search.rl.advantages import ZERO_ADVANTAGE, CreditMode, GroupAdvantages, SampleAdvantages, group_advantages
from lean_search.rl.claim_watch import proof_band
from lean_search.rl.grpo_groups import GroupSample, RewardConfig, RewardParts
from lean_search.rl.reward_replay import added
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import TreeRecord, from_json_object, read_tree
from lean_search.search.tactic_labels import TacticLabel, policy_tactics


class Outcome(StrEnum):
    COMPLETE_ON_GRAPH = "complete on graph"
    # Reaches the proof graph without a failing tactic but with a tactic charged within the block.
    CHARGED_ON_GRAPH = "charged on graph"
    FAILS_AFTER_GRAPH = "fails after graph"
    NEVER_ON_GRAPH = "never on graph"


class Transform(StrEnum):
    NONE = "none"
    # A sample failing after the proof graph gets no positive advantage, sequence or tactic.
    FAIL_NEVER_POSITIVE = "fail_never_positive"
    # A sample with a failing tactic gets at most 0 as its sequence advantage, its tactics keep theirs.
    EXPLANATION_CAP = "explanation_cap"
    # `PolicyDataConfig.cap_wasted_block_explanation`: the same for `GroupSample.has_wasted_tactic`.
    WASTE_CAP = "waste_cap"


class CreditKey(NamedTuple):
    variant: str
    outcome: Outcome
    band: str


@dataclass(frozen=True)
class CreditTally:
    """Weighted by the samples behind each group sample (its multiplicity)."""

    samples: int = 0
    sequence_advantage: float = 0.0
    positive_sequence_advantage: float = 0.0
    positive_sequences: int = 0
    negative_sequences: int = 0
    # Per-tactic advantages: up to and including the first proof-graph tactic (all of them without one), then the
    # continuation tactics by label.
    prefix: float = 0.0
    continued_on_graph: float = 0.0
    continued_on_graph_tactics: int = 0
    continued_failing: float = 0.0
    continued_failing_tactics: int = 0
    continued_other: float = 0.0
    continued_other_tactics: int = 0
    # Tactics after the block's first failing one, never run (the whole block, not only the continuation).
    masked_tactics: int = 0


@dataclass(frozen=True)
class GroupCount:
    groups: int = 0
    trained: int = 0
    trained_changed: int = 0


@dataclass(frozen=True)
class TreeCredit:
    trees: int = 0
    unreadable: int = 0
    credit: dict[CreditKey, CreditTally] = field(default_factory=dict)
    groups: dict[str, GroupCount] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    phase_config: TrainingPhaseConfig
    variants: dict[str, Variant]
    transforms: dict[str, Transform]
    # Per variant: what each tactic after a block's first failing one (never run) costs, charged to the failing one.
    masked_costs: dict[str, float]


def with_masked_cost(sample: GroupSample, cost: float) -> GroupSample:
    labels = [tactic.label for tactic in sample.tactics]
    masked = labels.count(TacticLabel.MASKED)
    if not masked or TacticLabel.FAILING not in labels:
        return sample
    index = labels.index(TacticLabel.FAILING)
    tactic = sample.tactics[index]
    charge = RewardParts(0.0, -cost * masked)
    assert tactic.parts is not None
    changed = (
        dataclasses.replace(tactic, parts=tactic.parts + charge)
        if tactic.gain is None
        else dataclasses.replace(tactic, gain=tactic.gain + charge)
    )
    return dataclasses.replace(sample, tactics=(*sample.tactics[:index], changed, *sample.tactics[index + 1 :]))


def merged[K](first: dict[K, object], second: Mapping[K, object]) -> dict[K, object]:
    result = dict(first)
    for key, value in second.items():
        result[key] = added(result[key], value) if key in result else value
    return result


def combined(first: TreeCredit, second: TreeCredit) -> TreeCredit:
    return TreeCredit(
        first.trees + second.trees,
        first.unreadable + second.unreadable,
        merged(first.credit, second.credit),
        merged(first.groups, second.groups),
    )


def sample_outcome(sample: GroupSample) -> Outcome:
    labels = [tactic.label for tactic in sample.tactics]
    if not sample.reaches_proof_graph:
        return Outcome.NEVER_ON_GRAPH
    after = labels[labels.index(TacticLabel.PROOF_GRAPH) + 1 :]
    if TacticLabel.FAILING in after:
        return Outcome.FAILS_AFTER_GRAPH
    return Outcome.CHARGED_ON_GRAPH if has_charged_tactic(sample) else Outcome.COMPLETE_ON_GRAPH


def never_positive(advantages: SampleAdvantages) -> SampleAdvantages:
    return dataclasses.replace(
        advantages,
        sequence=None if advantages.sequence is None else min(advantages.sequence, 0.0),
        tactics=tuple(None if value is None else min(value, 0.0) for value in advantages.tactics),
    )


def transformed(
    group_samples: Sequence[GroupSample], advantages: GroupAdvantages, transform: Transform
) -> GroupAdvantages:
    match transform:
        case Transform.NONE:
            return advantages
        case Transform.FAIL_NEVER_POSITIVE:
            return dataclasses.replace(
                advantages,
                samples=tuple(
                    never_positive(sample_advantages)
                    if sample_outcome(sample) == Outcome.FAILS_AFTER_GRAPH
                    else sample_advantages
                    for sample, sample_advantages in zip(group_samples, advantages.samples, strict=True)
                ),
            )
        case Transform.EXPLANATION_CAP | Transform.WASTE_CAP:
            return dataclasses.replace(
                advantages,
                samples=tuple(
                    capped(sample_advantages)
                    if (sample.has_wasted_tactic if transform == Transform.WASTE_CAP else sample.has_failing_tactic)
                    else sample_advantages
                    for sample, sample_advantages in zip(group_samples, advantages.samples, strict=True)
                ),
            )


def has_charged_tactic(sample: GroupSample) -> bool:
    return any(
        tactic.gain is not None and tactic.gain.total < 0 and tactic.label != TacticLabel.PROOF_GRAPH
        for tactic in sample.tactics
    )


def capped(advantages: SampleAdvantages) -> SampleAdvantages:
    sequence = advantages.sequence
    return dataclasses.replace(advantages, sequence=None if sequence is None else min(sequence, 0.0))


def sample_tally(sample: GroupSample, advantages: SampleAdvantages) -> CreditTally:
    labels = [tactic.label for tactic in sample.tactics]
    first_graph = labels.index(TacticLabel.PROOF_GRAPH) if TacticLabel.PROOF_GRAPH in labels else len(labels)
    values = [value or 0.0 for value in advantages.tactics]
    continued = list(zip(labels[first_graph + 1 :], values[first_graph + 1 :], strict=True))
    weight = sample.multiplicity
    sequence = advantages.sequence
    return CreditTally(
        samples=weight,
        sequence_advantage=weight * (sequence or 0.0),
        positive_sequence_advantage=weight * max(sequence or 0.0, 0.0),
        positive_sequences=weight * int(sequence is not None and sequence > ZERO_ADVANTAGE),
        negative_sequences=weight * int(sequence is not None and sequence < -ZERO_ADVANTAGE),
        prefix=weight * sum(values[: first_graph + 1]),
        continued_on_graph=weight * sum(value for label, value in continued if label == TacticLabel.PROOF_GRAPH),
        continued_on_graph_tactics=weight * sum(label == TacticLabel.PROOF_GRAPH for label, _ in continued),
        continued_failing=weight * sum(value for label, value in continued if label == TacticLabel.FAILING),
        continued_failing_tactics=weight * sum(label == TacticLabel.FAILING for label, _ in continued),
        continued_other=weight
        * sum(value for label, value in continued if label not in (TacticLabel.PROOF_GRAPH, TacticLabel.FAILING)),
        continued_other_tactics=weight
        * sum(
            label not in (TacticLabel.PROOF_GRAPH, TacticLabel.FAILING, TacticLabel.MASKED) for label, _ in continued
        ),
        masked_tactics=weight * labels.count(TacticLabel.MASKED),
    )


def tree_credit(record: TreeRecord, settings: Settings, band: str) -> TreeCredit:
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, settings.phase_config.reward.off_graph_min_expanded_nodes)
    credit: dict[CreditKey, CreditTally] = {}
    groups_by_variant: dict[str, GroupCount] = {}
    base_trained: dict[tuple[int, bool], bool] = {}
    for variant, reward_variant in settings.variants.items():
        counts = GroupCount()
        for built in variant_groups(record, labels, tactics, reward_variant, settings.phase_config):
            cost = settings.masked_costs[variant]
            group = dataclasses.replace(
                built, samples=tuple(with_masked_cost(sample, cost) for sample in built.samples)
            )
            advantages = transformed(group.samples, group_advantages(group), settings.transforms[variant])
            trained = advantages.has_signal(CreditMode.PER_TACTIC)
            if variant == BASE_VARIANT:
                base_trained[(group.node_id, group.feedback)] = trained
            changed = trained != base_trained[(group.node_id, group.feedback)]
            counts = added(counts, GroupCount(1, int(trained), int(changed)))
            if not trained:
                continue
            for sample, sample_advantages in zip(group.samples, advantages.samples, strict=True):
                key = CreditKey(variant, sample_outcome(sample), band)
                tally = sample_tally(sample, sample_advantages)
                credit[key] = added(credit[key], tally) if key in credit else tally
        groups_by_variant[variant] = counts
    return TreeCredit(1, 0, credit, groups_by_variant)


def file_credit(entry: TreeEntry, directory: Path, settings: Settings) -> TreeCredit:
    try:
        record = read_tree(directory / entry.file)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeCredit(trees=1, unreadable=1)
    return tree_credit(record, settings, proof_band(entry.difficulty))


def phase_settings(run: Path, phase: int, variants: Mapping[str, Mapping[str, object]]) -> Settings:
    config = from_json_object(
        TrainingPhaseConfig,
        tomllib.loads((run / "training" / f"phase_{phase:04d}.toml").read_text(encoding="utf-8")),
    )
    reward = dataclasses.asdict(config.reward)
    built = {BASE_VARIANT: Variant(config.reward)}
    transforms = {BASE_VARIANT: Transform.NONE}
    masked_costs = {BASE_VARIANT: 0.0}
    for name, overrides in variants.items():
        changes = dict(overrides)
        transforms[name] = Transform(changes.pop("transform", Transform.NONE))
        masked_costs[name] = float(changes.pop("masked_cost", 0.0))
        built[name] = Variant(from_json_object(RewardConfig, reward | changes))
    return Settings(config, built, transforms, masked_costs)


def tally_row(name: str, tally: CreditTally) -> str:
    samples = max(tally.samples, 1)
    return (
        f"| {name} | {tally.samples:,} | {tally.sequence_advantage:+.1f} | {tally.sequence_advantage / samples:+.3f} "
        f"| {tally.positive_sequences / samples:.0%} | {tally.positive_sequence_advantage:+.1f} | {tally.prefix:+.1f} "
        f"| {tally.continued_on_graph:+.1f} ({tally.continued_on_graph_tactics:,}) "
        f"| {tally.continued_failing:+.1f} ({tally.continued_failing_tactics:,}) "
        f"| {tally.continued_other:+.1f} ({tally.continued_other_tactics:,}) "
        f"| {tally.continued_on_graph + tally.continued_failing + tally.continued_other:+.1f} "
        f"| {tally.masked_tactics / samples:.2f} |"
    )


def phase_rows(credit: TreeCredit, variant: str) -> list[str]:
    rows = [
        "| outcome | samples | sum sequence adv | mean | share > 0 | positive sum | prefix tactics "
        "| continued on graph (tactics) "
        "| continued failing (tactics) | continued other (tactics) | continuation net | never-run tactics per sample |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_outcome: dict[Outcome, CreditTally] = {}
    for key, tally in credit.credit.items():
        if key.variant == variant:
            by_outcome[key.outcome] = added(by_outcome[key.outcome], tally) if key.outcome in by_outcome else tally
    for outcome in Outcome:
        if outcome in by_outcome:
            rows.append(tally_row(outcome.value, by_outcome[outcome]))
    return rows


def as_json(credit: TreeCredit) -> dict[str, object]:
    return {
        "trees": credit.trees,
        "unreadable": credit.unreadable,
        "credit": [
            {"variant": key.variant, "outcome": key.outcome.value, "band": key.band, **dataclasses.asdict(tally)}
            for key, tally in sorted(credit.credit.items())
        ],
        "groups": {variant: dataclasses.asdict(count) for variant, count in credit.groups.items()},
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--trees", type=Path, help="another tree store, labelled with the run's phase configs")
    parser.add_argument("--phases", type=int, nargs="+", required=True)
    parser.add_argument("--config-phase", type=int, help="the run's phase config to use for every phase")
    parser.add_argument("--variants", default="{}", help="JSON: name -> [reward] overrides, or transform")
    parser.add_argument("--trees-per-phase", type=int, default=0, help="0: every tree")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    store = TreeStore(arguments.trees or arguments.run / "trees")
    variants = json.loads(arguments.variants)
    results = {}
    with contextlib.ExitStack() as stack:
        pool = stack.enter_context(Pool(arguments.workers, maxtasksperchild=40))
        for phase in arguments.phases:
            settings = phase_settings(arguments.run, arguments.config_phase or phase, variants)
            entries = sampled_entries(store, phase, arguments.trees_per_phase)
            task = partial(file_credit, directory=store.directory, settings=settings)
            credit = TreeCredit()
            for tree in pool.imap_unordered(task, entries, chunksize=2):
                credit = combined(credit, tree)
            results[phase] = as_json(credit)
            print(f"\n## Phase {phase}: {credit.trees} trees ({credit.unreadable} unreadable)\n", flush=True)
            for variant in settings.variants:
                print(f"### {variant}: groups {credit.groups[variant]}\n")
                print("\n".join(phase_rows(credit, variant)) + "\n", flush=True)
            arguments.output.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
