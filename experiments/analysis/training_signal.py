"""The training signal four policy-training schemes would draw from the same recorded trees of grpo_loop_v1, scored
with the production code (labels, rewards, groups, token credit) under today's [reward] of
experiments/configs/grpo/phase.toml:

- per_tactic: the loop's search-tree GRPO (`policy_data.tree_policy_data`, credit "per_tactic");
- sequence: the same groups with credit "sequence" (every sampled token gets the sample's score minus the baseline);
- outcome: in the same expansion groups, reward 1 for a sample with a tactic on the proof graph, else 0, minus the
  group's mean, on every sampled token (no division by a standard deviation, like the loop);
- expert iteration: the round's selection (`expert_iteration_data.proof_graph_completions` and `CompletionSelector`)
  per phase.

    PYTHONPATH=src python experiments/analysis/training_signal.py --phases 1 2 3 4 --trees-per-phase 160
    PYTHONPATH=src python experiments/analysis/training_signal.py --phases 16 17 ... 26 --trees-per-phase 100

Trees per phase: the first `--trees-per-phase` present locally in a seeded hash order of their files (the order the
sample was downloaded in). Prints markdown tables per phase range and per phase.
"""

import argparse
import hashlib
import json
import tomllib
import zlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from multiprocessing import Pool
from pathlib import Path

from lean_search.policy.expander import load_tokenizer
from lean_search.rl.advantages import ZERO_ADVANTAGE, CreditMode, SampleAdvantages
from lean_search.rl.expert_iteration_data import (
    CompletionFilter,
    CompletionSelector,
    ExpertIterationDataConfig,
    TreeBlocks,
    TreeCompletions,
    proof_graph_completions,
)
from lean_search.rl.grpo_groups import REACHED_STATE_LABELS, GroupSample, PolicyGroup, RewardConfig
from lean_search.rl.health_checks import read_rejected_versions
from lean_search.rl.policy_data import (
    PolicyDataConfig,
    PolicySequence,
    PolicyTokenizer,
    PolicyTree,
    policy_sequence,
    tree_policy_data,
)
from lean_search.rl.reward_replay import added, added_all
from lean_search.rl.token_credit import TokenSegment
from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.search.graph_labels import NodeClass
from lean_search.search.records import TreeRecord, from_json_object, read_tree
from lean_search.search.tactic_labels import TacticLabel

REPOSITORY = Path(__file__).resolve().parents[2]
PHASE_CONFIG = REPOSITORY / "experiments" / "configs" / "grpo" / "phase.toml"
EXPERT_ITERATION_CONFIG = REPOSITORY / "experiments" / "configs" / "grpo" / "expert_iteration_1_b.toml"
DATASET = REPOSITORY / "node_backup" / "2026-11-01" / "hf_dataset"
METRICS = REPOSITORY / "node_backup" / "2026-11-01" / "hf_run" / "run_logs" / "metrics"
# The policy's tokenizer is Qwen3.5's; the 2B model's copy is the one cached locally. Recorded token ids that do not
# decode to the recorded text would show up as token mismatches.
TOKENIZER = "Qwen/Qwen3.5-2B"
SAMPLE_SEED = "signal-sample"
WASTED_LABELS = (TacticLabel.FAILING, TacticLabel.NO_PROGRESS, TacticLabel.REDUNDANT_HYPOTHESIS)


class Scheme(StrEnum):
    PER_TACTIC = "a per-tactic"
    SEQUENCE = "b sequence"
    OUTCOME = "c outcome"


SCHEMES = tuple(Scheme)


@dataclass(frozen=True)
class SignalTally:
    """Summed over trees; samples are recorded completions (one training sequence each)."""

    contributing_solved_trees: int = 0
    contributing_unsolved_trees: int = 0
    groups: int = 0
    samples: int = 0
    # Samples with a positive token, with a negative token (a per-tactic sample can have both).
    positive_samples: int = 0
    negative_samples: int = 0
    positive_tokens: int = 0
    negative_tokens: int = 0
    magnitude: float = 0.0
    unsolved_magnitude: float = 0.0
    # Samples of solved trees without a proof-graph tactic, and samples with one.
    off_graph_magnitude: float = 0.0
    on_graph_magnitude: float = 0.0
    explanation_magnitude: float = 0.0
    # The magnitude on tokens whose sample's outcome advantage has the same sign, the opposite sign, or is zero.
    outcome_agreeing: float = 0.0
    outcome_opposing: float = 0.0
    outcome_zero: float = 0.0


@dataclass(frozen=True)
class ExpansionCounts:
    """Policy expansions (feedback rounds included) by where they are, and those whose samples' first tactics include
    both a reached state and a failure or no-op: a local signal without any proof."""

    on_proof_graph: int = 0
    off_proof_graph_solved: int = 0
    unsolved: int = 0
    mixed_off_proof_graph_solved: int = 0
    mixed_unsolved: int = 0
    sampled_tokens: int = 0


@dataclass(frozen=True)
class TreeSignal:
    """Summed over trees."""

    trees: int = 0
    solved: int = 0
    unreadable: int = 0
    # Per `SCHEMES`.
    tallies: tuple[SignalTally, ...] = tuple(SignalTally() for _ in SCHEMES)
    expansions: ExpansionCounts = field(default_factory=ExpansionCounts)
    token_mismatches: int = 0


@dataclass(frozen=True)
class TreeOutcome:
    signal: TreeSignal
    # The tree's expert-iteration candidates, which the selection pools per phase.
    completions: TreeCompletions = field(default_factory=TreeCompletions)


@dataclass(frozen=True)
class ExpertIterationCounts:
    contributing_trees: int
    kept_before_selection: int
    selected: int
    selected_completion_tokens: int


@dataclass(frozen=True)
class PhaseSignal:
    phase: int
    trees_in_phase: int
    signal: TreeSignal
    expert_iteration: ExpertIterationCounts

    @property
    def scale(self) -> float:
        return self.trees_in_phase / self.signal.trees


@dataclass(frozen=True)
class Settings:
    phase_config: TrainingPhaseConfig
    expert_iteration: ExpertIterationDataConfig
    completion_filter: CompletionFilter


def on_proof_graph(sample: GroupSample) -> bool:
    return any(tactic.label == TacticLabel.PROOF_GRAPH for tactic in sample.tactics)


def outcome_advantages(group: PolicyGroup) -> tuple[float, ...]:
    rewards = [float(on_proof_graph(sample)) for sample in group.samples]
    weights = [sample.multiplicity for sample in group.samples]
    mean = sum(reward * weight for reward, weight in zip(rewards, weights, strict=True)) / sum(weights)
    return tuple(reward - mean for reward in rewards)


def sign(value: float) -> int:
    return 0 if abs(value) <= ZERO_ADVANTAGE else (1 if value > 0 else -1)


def sequence_tally(
    sequences: Sequence[PolicySequence],
    samples_by_edge: dict[int, GroupSample],
    outcome_by_edge: dict[int, float],
    solved: bool,
) -> SignalTally:
    tallies = []
    for sequence in sequences:
        values = [
            (advantage, segment)
            for advantage, trained, segment in zip(
                sequence.advantages, sequence.trained, sequence.segments, strict=True
            )
            if trained and sign(advantage) != 0
        ]
        if not values:
            continue
        magnitude = sum(abs(advantage) for advantage, _ in values)
        outcome_sign = sign(outcome_by_edge[sequence.edge_id])
        on_graph = on_proof_graph(samples_by_edge[sequence.edge_id])
        tallies.append(
            SignalTally(
                samples=1,
                positive_samples=any(advantage > 0 for advantage, _ in values),
                negative_samples=any(advantage < 0 for advantage, _ in values),
                positive_tokens=sum(advantage > 0 for advantage, _ in values),
                negative_tokens=sum(advantage < 0 for advantage, _ in values),
                magnitude=magnitude,
                unsolved_magnitude=0.0 if solved else magnitude,
                off_graph_magnitude=magnitude if solved and not on_graph else 0.0,
                on_graph_magnitude=magnitude if on_graph else 0.0,
                explanation_magnitude=sum(
                    abs(advantage) for advantage, segment in values if segment == TokenSegment.EXPLANATION
                ),
                outcome_agreeing=sum(abs(advantage) for advantage, _ in values if sign(advantage) == outcome_sign),
                outcome_opposing=sum(abs(advantage) for advantage, _ in values if sign(advantage) == -outcome_sign),
                outcome_zero=magnitude if outcome_sign == 0 else 0.0,
            )
        )
    total = added_all(tallies, SignalTally())
    return added(
        total,
        SignalTally(
            contributing_solved_trees=int(solved and total.samples > 0),
            contributing_unsolved_trees=int(not solved and total.samples > 0),
        ),
    )


def outcome_sequences(
    tree: PolicyTree, tokenizer: PolicyTokenizer, outcome_by_edge: dict[int, float]
) -> tuple[list[PolicySequence], int]:
    """The outcome scheme's sequences (sequence credit, no prompt: only the completion tokens are counted) and its
    groups with a non-zero advantage."""
    texts_by_prompt = {(expansion.node_id, expansion.feedback): expansion for expansion in tree.texts}
    sequences = []
    groups = 0
    for group in tree.groups:
        advantages = [outcome_by_edge[sample.edge_ids[0]] for sample in group.samples]
        if all(sign(advantage) == 0 for advantage in advantages):
            continue
        groups += 1
        expansion = texts_by_prompt.get((group.node_id, group.feedback))
        if expansion is None:
            continue
        for sample, advantage in zip(group.samples, advantages, strict=True):
            credit = SampleAdvantages(advantage, tuple(None for _ in sample.tactics), None)
            for completion in expansion.completions:
                if completion.edge_id in sample.edge_ids:
                    sequence, _ = policy_sequence(
                        tokenizer, group, expansion, (), completion, 1.0, credit, CreditMode.SEQUENCE
                    )
                    sequences.append(sequence)
    return sequences, groups


def expansion_counts(record: TreeRecord, blocks: TreeBlocks) -> ExpansionCounts:
    solved = blocks.labels.solved
    counts = []
    for expansion in record.expansions:
        firsts = [outcomes[0].label for item in expansion.completions if (outcomes := blocks.outcomes(item))]
        mixed = any(label in REACHED_STATE_LABELS for label in firsts) and any(
            label in WASTED_LABELS for label in firsts
        )
        sampled_tokens = sum(len(item.tokens.token_ids) for item in expansion.completions)
        if not solved:
            counts.append(ExpansionCounts(unsolved=1, mixed_unsolved=int(mixed), sampled_tokens=sampled_tokens))
        elif blocks.labels.node_classes[expansion.node_id] == NodeClass.PROOF_GRAPH:
            counts.append(ExpansionCounts(on_proof_graph=1, sampled_tokens=sampled_tokens))
        else:
            counts.append(
                ExpansionCounts(
                    off_proof_graph_solved=1, mixed_off_proof_graph_solved=int(mixed), sampled_tokens=sampled_tokens
                )
            )
    return added_all(counts, ExpansionCounts())


def tree_outcome(record: TreeRecord, tokenizer: PolicyTokenizer, settings: Settings) -> TreeOutcome:
    labelled = label_phase_data([record], settings.phase_config)
    tree = labelled.policy_trees[0]
    solved = record.result.proved
    samples_by_edge = {
        edge_id: sample for group in tree.groups for sample in group.samples for edge_id in sample.edge_ids
    }
    outcome_by_edge = {
        edge_id: advantage
        for group in tree.groups
        for sample, advantage in zip(group.samples, outcome_advantages(group), strict=True)
        for edge_id in sample.edge_ids
    }
    tallies = []
    mismatches = 0
    for credit in (CreditMode.PER_TACTIC, CreditMode.SEQUENCE):
        parts = tree_policy_data(tree, tokenizer, PolicyDataConfig(credit=credit))
        mismatches = parts.mismatches
        tally = sequence_tally(parts.sequences, samples_by_edge, outcome_by_edge, solved)
        tallies.append(added(tally, SignalTally(groups=len(parts.trained_groups))))
    sequences, outcome_groups = outcome_sequences(tree, tokenizer, outcome_by_edge)
    tally = sequence_tally(sequences, samples_by_edge, outcome_by_edge, solved)
    tallies.append(added(tally, SignalTally(groups=outcome_groups)))
    blocks = TreeBlocks(record, settings.expert_iteration)
    completions = proof_graph_completions(record, tokenizer, settings.expert_iteration, settings.completion_filter)
    signal = TreeSignal(
        trees=1,
        solved=int(solved),
        tallies=tuple(tallies),
        expansions=expansion_counts(record, blocks),
        token_mismatches=mismatches,
    )
    return TreeOutcome(signal, completions)


WORKER_TOKENIZER: list[PolicyTokenizer] = []


def start_worker() -> None:
    WORKER_TOKENIZER.append(load_tokenizer(TOKENIZER))


def file_outcome(entry: TreeEntry, directory: Path, settings: Settings) -> TreeOutcome:
    try:
        record = read_tree(directory / entry.file)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeOutcome(TreeSignal(trees=1, unreadable=1))
    return tree_outcome(record, WORKER_TOKENIZER[0], settings)


def sampled_entries(store: TreeStore, phase: int, count: int) -> list[TreeEntry]:
    ordered = sorted(
        store.phase_entries(phase), key=lambda entry: hashlib.sha256(f"{SAMPLE_SEED}\0{entry.file}".encode()).digest()
    )
    return [entry for entry in ordered if (store.directory / entry.file).exists()][:count]


def expert_iteration_counts(
    outcomes: Sequence[TreeOutcome], config: ExpertIterationDataConfig
) -> ExpertIterationCounts:
    selector = CompletionSelector(config)
    for outcome in outcomes:
        selector.add(outcome.completions)
    selected = selector.selected()
    examples = [*selected.train, *selected.validation]
    return ExpertIterationCounts(
        contributing_trees=sum(bool(outcome.completions.completions) for outcome in outcomes),
        kept_before_selection=selector.counts.kept,
        selected=len(examples),
        selected_completion_tokens=sum(example.tokenized.completion_token_count for example in examples),
    )


def percent(part: float, whole: float) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def scheme_rows(phases: Sequence[PhaseSignal]) -> list[str]:
    """Per scheme, per phase on average (each phase's sample scaled to its trees)."""
    count = len(phases)
    rows = [
        "| scheme | trees contributing (solved / unsolved) | groups | samples (with + / with -) | tokens + / - "
        "| unsolved / off-graph / on-graph share of sum abs(adv) | explanation share "
        "| agree / oppose / zero vs outcome | mean abs(adv) per token |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, scheme in enumerate(SCHEMES):
        scaled = [(phase.scale, phase.signal.tallies[index]) for phase in phases]

        def mean(name: str, scaled: Sequence[tuple[float, SignalTally]] = scaled) -> float:
            return sum(scale * getattr(tally, name) for scale, tally in scaled) / count

        total = mean("magnitude")
        rows.append(
            f"| {scheme} | {mean('contributing_solved_trees'):,.0f} / {mean('contributing_unsolved_trees'):,.0f} "
            f"| {mean('groups'):,.0f} | {mean('samples'):,.0f} ({mean('positive_samples'):,.0f} / "
            f"{mean('negative_samples'):,.0f}) | {mean('positive_tokens') / 1e3:,.0f}k / "
            f"{mean('negative_tokens') / 1e3:,.0f}k | {percent(mean('unsolved_magnitude'), total)} / "
            f"{percent(mean('off_graph_magnitude'), total)} / {percent(mean('on_graph_magnitude'), total)} "
            f"| {percent(mean('explanation_magnitude'), total) if scheme == Scheme.PER_TACTIC else '-'} "
            f"| {percent(mean('outcome_agreeing'), total)} / {percent(mean('outcome_opposing'), total)} / "
            f"{percent(mean('outcome_zero'), total)} "
            f"| {total / (mean('positive_tokens') + mean('negative_tokens')):.3f} |"
        )
    return rows


def phase_rows(phases: Sequence[PhaseSignal]) -> list[str]:
    rows = [
        "| phase | trees (sampled) | solved | groups a / b / c | tokens with adv. a / b / c | sampled tokens "
        "| EI trees / kept / selected (tokens) |",
        "|---|---|---|---|---|---|---|",
    ]
    for phase in phases:
        signal = phase.signal
        tallies = signal.tallies
        scale = phase.scale
        tokens = " / ".join(
            f"{scale * (tally.positive_tokens + tally.negative_tokens) / 1e6:.2f}M" for tally in tallies
        )
        expert = phase.expert_iteration
        rows.append(
            f"| {phase.phase} | {phase.trees_in_phase} ({signal.trees}) | {percent(signal.solved, signal.trees)} "
            f"| {' / '.join(f'{scale * tally.groups:,.0f}' for tally in tallies)} | {tokens} "
            f"| {scale * signal.expansions.sampled_tokens / 1e6:.1f}M "
            f"| {scale * expert.contributing_trees:,.0f} / {scale * expert.kept_before_selection:,.0f} / "
            f"{scale * expert.selected:,.0f} "
            f"({scale * expert.selected_completion_tokens / 1e6:.2f}M) |"
        )
    return rows


def expansion_lines(phases: Sequence[PhaseSignal]) -> list[str]:
    counts = added_all([phase.signal.expansions for phase in phases], ExpansionCounts())
    total = counts.on_proof_graph + counts.off_proof_graph_solved + counts.unsolved
    mismatches = sum(phase.signal.token_mismatches for phase in phases)
    unreadable = sum(phase.signal.unreadable for phase in phases)
    return [
        f"Expansions in the sample: {total:,}; at proof-graph nodes {percent(counts.on_proof_graph, total)}, off the "
        f"proof graph in solved trees {percent(counts.off_proof_graph_solved, total)} (mixed first tactics "
        f"{percent(counts.mixed_off_proof_graph_solved, counts.off_proof_graph_solved)}), in unsolved trees "
        f"{percent(counts.unsolved, total)} (mixed {percent(counts.mixed_unsolved, counts.unsolved)}).",
        f"Token mismatches (recorded ids not decoding to the text): {mismatches}; unreadable trees: {unreadable}.",
    ]


@dataclass(frozen=True)
class LoggedUpdate:
    """One phase's policy update as grpo.jsonl and health.jsonl logged it; ratios and clipping of the last pass."""

    phase: int
    trained_from: int
    groups_trained: int
    sequences: int
    trained_tokens: int
    local_advantage_share: float
    clip_fraction: float
    kl_to_data_policy: float
    kl_to_starting_policy: float | None
    passes: int
    positive_ratio: float
    positive_clip_fraction: float
    negative_ratio: float


def logged_updates(metrics: Path) -> list[LoggedUpdate]:
    """A phase logged twice (a replayed health check) keeps its last line."""
    starting_kl: dict[int, float] = {}
    with (metrics / "health.jsonl").open(encoding="utf-8") as lines:
        for line in lines:
            entry = json.loads(line)
            starting_kl[entry["phase"]] = entry["fields"]["measured"]["kl_to_starting_policy"]
    updates = []
    with (metrics / "grpo.jsonl").open(encoding="utf-8") as lines:
        for line in lines:
            entry = json.loads(line)
            fields = entry["fields"]
            passes = fields["ratios_by_pass"]
            last = passes[max(passes, key=int)]
            updates.append(
                LoggedUpdate(
                    phase=entry["phase"],
                    trained_from=entry["policy_version"],
                    groups_trained=fields["groups_trained"],
                    sequences=fields["sequences"],
                    trained_tokens=fields["trained_tokens"],
                    local_advantage_share=fields["local_advantage_share"],
                    clip_fraction=fields["clip_fraction"],
                    kl_to_data_policy=fields["kl_to_behaviour_policy"],
                    kl_to_starting_policy=starting_kl.get(entry["phase"]),
                    passes=len(passes),
                    positive_ratio=last["positive"]["mean_ratio"],
                    positive_clip_fraction=last["positive"]["clip_fraction"],
                    negative_ratio=last["negative"]["mean_ratio"],
                )
            )
    return updates


def logged_rows(updates: Sequence[LoggedUpdate]) -> list[str]:
    rows = [
        "| phase | from v | passes | groups | sequences | trained tokens | local share | clip | KL to data policy "
        "| KL to v0 | ratio + (clip +) | ratio - |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for update in updates:
        starting = "-" if update.kl_to_starting_policy is None else f"{update.kl_to_starting_policy:.3g}"
        rows.append(
            f"| {update.phase} | {update.trained_from} | {update.passes} | {update.groups_trained:,} "
            f"| {update.sequences:,} | {update.trained_tokens / 1e6:.2f}M | {update.local_advantage_share:.3f} "
            f"| {update.clip_fraction:.3f} | {update.kl_to_data_policy:.3g} | {starting} "
            f"| {update.positive_ratio:.4f} ({update.positive_clip_fraction:.3f}) | {update.negative_ratio:.4g} |"
        )
    return rows


def load_settings(dataset: Path) -> Settings:
    phase_config = tomllib.loads(PHASE_CONFIG.read_text(encoding="utf-8"))
    expert_iteration = tomllib.loads(EXPERT_ITERATION_CONFIG.read_text(encoding="utf-8"))["data"]
    return Settings(
        phase_config=TrainingPhaseConfig(reward=from_json_object(RewardConfig, phase_config["reward"])),
        expert_iteration=from_json_object(ExpertIterationDataConfig, expert_iteration),
        # Every version from 0 (the round itself started at the reward fix); held-out statements are never fed.
        completion_filter=CompletionFilter(
            minimum_version=0,
            rejected_versions=frozenset(read_rejected_versions(dataset / "run_logs" / "rejected_versions.jsonl")),
        ),
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--phases", type=int, nargs="+", default=[])
    parser.add_argument("--metrics", type=Path, default=METRICS)
    parser.add_argument("--logged", action="store_true", help="print the logged updates of every phase and stop")
    parser.add_argument("--trees-per-phase", type=int, default=100)
    parser.add_argument("--workers", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.logged:
        print("\n".join(logged_rows(logged_updates(arguments.metrics))))
        return
    settings = load_settings(arguments.dataset)
    store = TreeStore(arguments.dataset / "search_trees")
    phases = []
    with Pool(arguments.workers, initializer=start_worker, maxtasksperchild=50) as pool:
        for phase in arguments.phases:
            entries = sampled_entries(store, phase, arguments.trees_per_phase)
            outcomes = list(
                pool.imap_unordered(
                    partial(file_outcome, directory=store.directory, settings=settings), entries, chunksize=4
                )
            )
            signal = added_all([outcome.signal for outcome in outcomes], TreeSignal())
            expert = expert_iteration_counts(outcomes, settings.expert_iteration)
            phases.append(PhaseSignal(phase, len(store.phase_entries(phase)), signal, expert))
            print(f"phase {phase}: {signal.trees} trees sampled", flush=True)
    repeated = Counter(
        entry.problem_name for entry in store.entries if entry.phase in arguments.phases and entry.proved
    )
    print(f"\nPhases {arguments.phases[0]}-{arguments.phases[-1]}, per phase on average:\n")
    print("\n".join(scheme_rows(phases)))
    print()
    print("\n".join(phase_rows(phases)))
    print()
    print("\n".join(expansion_lines(phases)))
    print(
        f"Solved trees in these phases: {sum(repeated.values()):,}, distinct statements {len(repeated):,} "
        f"(statements solved more than once: {sum(count > 1 for count in repeated.values()):,})."
    )


if __name__ == "__main__":
    main()
