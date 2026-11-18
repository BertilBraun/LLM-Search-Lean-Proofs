"""Where per-tactic GRPO puts its advantage on samples opening with a bare `have` claim, on a loop's recorded trees,
with the production code path (labels, rewards, groups, group advantages, token credit), under the phase's own reward
and under reward variants (overrides of `[reward]`), compared on the same groups.

    PYTHONPATH=src python experiments/analysis/bare_have_credit.py --run /workspace/runs/followup_A --phases 1 2 3 \
        --variants '{"fix": {"claims_earn_progress": false, "unproved_claim_cost": 0.3},
                     "never positive": {"transform": "open_claim_never_positive"}}' --check-production --output a.json

A variant overrides the phase's `[reward]`; `transform` (`Transform`) replays an alternative without a production
switch, `extra` its cost. Groups are built as the trainer builds them (`training_phase.label_phase_data`: the trees'
recorded value estimates, which enter only through μ, the phase's excluded versions); with --check-production every
sequence's token advantages under the phase's reward are asserted equal to `policy_data.tree_policy_data`'s on those
groups. --no-token-credit keeps the sequence advantages only (no tokenizer; the per-band readings), --workers 1 runs in
this one process. Samples are recorded completions (one training sequence each) of the groups the trainer keeps,
keyed by opening (`claim_watch.Opening`: the block's first top-level tactic as `tree_summary.block_habits` counts it, a
bare `have` by what its claim became), whether the sample reaches the proof graph, and the statement's probe band
(`claim_watch.proof_band`). Run on the node on 2026-11-18 over arm A's phases 1-7, step 2's v0 phase and the 2e-5
start's two phases (`src/lean_search/rl/README.md`, "Claims").
"""

import argparse
import contextlib
import dataclasses
import hashlib
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

from lean_search.policy.expander import load_tokenizer
from lean_search.rl.advantages import (
    ZERO_ADVANTAGE,
    CreditMode,
    GroupAdvantages,
    SampleAdvantages,
    group_advantages,
)
from lean_search.rl.claim_watch import BARE_OPENINGS, Opening, proof_band, sample_openings
from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardConfig, RewardParts, policy_groups
from lean_search.rl.policy_data import (
    CompletionTokens,
    PolicyDataConfig,
    PolicyTokenizer,
    PolicyTree,
    completion_tokens,
    tree_policy_data,
)
from lean_search.rl.reward_replay import added, added_all
from lean_search.rl.token_credit import tactic_position, token_credits
from lean_search.rl.training_phase import TrainingPhaseConfig, groups_not_sampled_by
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.search.graph_labels import GraphLabels, label_graph
from lean_search.search.records import TreeRecord, from_json_object, read_tree
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome, policy_tactics
from lean_search.search.texts import SampledCompletion, overlaps
from lean_search.value.graph_targets import recorded_estimates

SAMPLE_SEED = "bare-have-credit"
TOKENIZER = "Qwen/Qwen3.5-4B"
BASE_VARIANT = "phase reward"


class CreditKey(NamedTuple):
    variant: str
    opening: Opening
    on_graph: bool
    # The statement's probe band (`claim_watch.proof_band`).
    band: str


@dataclass(frozen=True)
class CreditTally:
    """Summed over the trained sequences of a key; advantages summed over trained tokens."""

    sequences: int = 0
    tokens: int = 0
    total: float = 0.0
    positive: float = 0.0
    negative: float = 0.0
    explanation: float = 0.0
    explanation_tokens: int = 0
    first_tactic: float = 0.0
    first_tactic_tokens: int = 0
    # The first tactic's first token: the `have` keyword of a have opening.
    first_token: float = 0.0
    # The tokens after the first tactic up to the next tactic's span (the line end deciding between `:=` and a new
    # line), or the closing part after a one-tactic block.
    after_first: float = 0.0
    later_tactics: float = 0.0
    closing: float = 0.0
    sequence_advantage: float = 0.0
    positive_sequences: int = 0
    negative_sequences: int = 0
    first_tactic_advantage: float = 0.0


@dataclass(frozen=True)
class SampleCount:
    """First-round policy samples of every tree, by where they train."""

    samples: int = 0
    in_groups: int = 0
    in_trained_groups: int = 0


class SampleKey(NamedTuple):
    opening: Opening
    on_graph: bool
    band: str


@dataclass(frozen=True)
class GroupCount:
    groups: int = 0
    trained: int = 0
    with_bare_have: int = 0
    # Against the phase's reward: trained under only one of the two, or a sample's explanation advantage changed sign.
    trained_changed: int = 0
    sign_changed: int = 0
    # Sum over trained groups of the multiplicity-weighted positive explanation advantage of samples reaching the proof
    # graph: the signal on proof-graph progress a fix must keep.
    proof_graph_positive: float = 0.0


@dataclass(frozen=True)
class TreeCredit:
    trees: int = 0
    unreadable: int = 0
    mismatches: int = 0
    credit: dict[CreditKey, CreditTally] = field(default_factory=dict)
    samples: dict[SampleKey, SampleCount] = field(default_factory=dict)
    groups: dict[str, GroupCount] = field(default_factory=dict)


def merged[K](first: dict[K, object], second: Mapping[K, object]) -> dict[K, object]:
    result = dict(first)
    for key, value in second.items():
        result[key] = added(result[key], value) if key in result else value
    return result


def combined(first: TreeCredit, second: TreeCredit) -> TreeCredit:
    return TreeCredit(
        first.trees + second.trees,
        first.unreadable + second.unreadable,
        first.mismatches + second.mismatches,
        merged(first.credit, second.credit),
        merged(first.samples, second.samples),
        merged(first.groups, second.groups),
    )


@dataclass(frozen=True)
class TokenPositions:
    """Per completion token: -1 explanation, k for tactic k (the gap before it included), the tactic count for the
    closing part, None inserted; as `token_credits` places them."""

    positions: tuple[int | None, ...]
    # Tokens of the first tactic's span that start it, and those between it and the next tactic's span.
    first_token: int | None
    after_first: frozenset[int]


def token_positions(tokens: CompletionTokens, completion: SampledCompletion, tactic_count: int) -> TokenPositions:
    spans = completion.tactic_spans if tokens.offsets is not None else ()
    offsets = tokens.offsets or tuple((0, 0) for _ in tokens.token_ids)
    by_position = bool(spans) and len(spans) == tactic_count
    positions: list[int | None] = []
    for index, token in enumerate(offsets):
        if index in tokens.inserted:
            positions.append(None)
        elif not by_position or (token[0] < spans[0].start and token[1] <= spans[0].start):
            positions.append(-1)
        else:
            positions.append(tactic_position(token, spans))
    first_token = next((index for index, position in enumerate(positions) if position == 0), None)
    after_first = frozenset(
        index
        for index, position in enumerate(positions)
        if by_position
        and position is not None
        and position >= 1
        and not any(overlaps(offsets[index], span) for span in spans[1:2])
        and (len(spans) == 1 or offsets[index][1] <= spans[1].start)
        and offsets[index][0] >= spans[0].end - 1
    )
    return TokenPositions(tuple(positions), first_token, after_first)


def sequence_tally(
    tactic_count: int,
    advantages: Sequence[float],
    trained: Sequence[bool],
    positions: TokenPositions,
    sequence_advantage: float | None,
    first_tactic_advantage: float | None,
) -> CreditTally:
    values = [
        (index, advantage, position)
        for index, (advantage, is_trained, position) in enumerate(
            zip(advantages, trained, positions.positions, strict=True)
        )
        if is_trained
    ]
    explanation = [advantage for _, advantage, position in values if position == -1]
    first = [advantage for _, advantage, position in values if position == 0]
    return CreditTally(
        sequences=1,
        tokens=len(values),
        total=sum(advantage for _, advantage, _ in values),
        positive=sum(advantage for _, advantage, _ in values if advantage > 0),
        negative=sum(advantage for _, advantage, _ in values if advantage < 0),
        explanation=sum(explanation),
        explanation_tokens=len(explanation),
        first_tactic=sum(first),
        first_tactic_tokens=len(first),
        first_token=sum(advantage for index, advantage, _ in values if index == positions.first_token),
        after_first=sum(advantage for index, advantage, _ in values if index in positions.after_first),
        later_tactics=sum(
            advantage
            for index, advantage, position in values
            if position is not None and position >= 1 and index not in positions.after_first and position < tactic_count
        ),
        closing=sum(
            advantage
            for index, advantage, position in values
            if position == tactic_count and tactic_count > 0 and index not in positions.after_first
        ),
        sequence_advantage=sequence_advantage or 0.0,
        positive_sequences=int(sequence_advantage is not None and sequence_advantage > ZERO_ADVANTAGE),
        negative_sequences=int(sequence_advantage is not None and sequence_advantage < -ZERO_ADVANTAGE),
        first_tactic_advantage=first_tactic_advantage or 0.0,
    )


def sequence_only(advantages: SampleAdvantages) -> CreditTally:
    sequence = advantages.sequence
    return CreditTally(
        sequences=1,
        sequence_advantage=sequence or 0.0,
        positive_sequences=int(sequence is not None and sequence > ZERO_ADVANTAGE),
        negative_sequences=int(sequence is not None and sequence < -ZERO_ADVANTAGE),
        first_tactic_advantage=(advantages.tactics[0] if advantages.tactics else None) or 0.0,
    )


def signature(advantages: GroupAdvantages) -> tuple[int, ...]:
    return tuple(
        0 if sample.sequence is None or abs(sample.sequence) <= ZERO_ADVANTAGE else (1 if sample.sequence > 0 else -1)
        for sample in advantages.samples
    )


class Transform(StrEnum):
    """Alternatives replayed here without a production switch."""

    NONE = "none"
    # The block's first unproved claim costs `extra` more.
    UNPROVED_CLAIM_EXTRA = "unproved_claim_extra"
    # Only a claim its block leaves open earns no progress (score-equivalent to deferring a claim's δ to its proof).
    OPEN_CLAIM_PROGRESS_DROPPED = "open_claim_progress_dropped"
    # A sample whose block leaves a claim open gets no positive advantage on any token.
    OPEN_CLAIM_NEVER_POSITIVE = "open_claim_never_positive"


@dataclass(frozen=True)
class Variant:
    reward: RewardConfig
    transform: Transform = Transform.NONE
    extra: float = 0.0


@dataclass(frozen=True)
class Settings:
    phase_config: TrainingPhaseConfig
    variants: dict[str, Variant]
    check_production: bool
    # False: sequence advantages only, no token placement (no tokenizer; several times faster).
    token_credit: bool = True


def with_unproved_claim_extra(sample: GroupSample, extra: float) -> GroupSample:
    labels = [tactic.label for tactic in sample.tactics]
    if TacticLabel.UNPROVED_CLAIM not in labels:
        return sample
    index = labels.index(TacticLabel.UNPROVED_CLAIM)
    tactic = sample.tactics[index]
    cost = RewardParts(0.0, -extra)
    assert tactic.parts is not None
    changed = (
        dataclasses.replace(tactic, parts=tactic.parts + cost)
        if tactic.gain is None
        else dataclasses.replace(tactic, gain=tactic.gain + cost)
    )
    return dataclasses.replace(sample, tactics=(*sample.tactics[:index], changed, *sample.tactics[index + 1 :]))


def open_claims_only(tactics: Mapping[int, Sequence[TacticOutcome]]) -> dict[int, tuple[TacticOutcome, ...]]:
    return {
        edge: tuple(
            dataclasses.replace(outcome, adds_claim=outcome.adds_claim and outcome.leaves_claim_open)
            for outcome in outcomes
        )
        for edge, outcomes in tactics.items()
    }


def never_positive(advantages: SampleAdvantages) -> SampleAdvantages:
    return dataclasses.replace(
        advantages,
        sequence=None if advantages.sequence is None else min(advantages.sequence, 0.0),
        tactics=tuple(None if value is None else min(value, 0.0) for value in advantages.tactics),
    )


def variant_groups(
    record: TreeRecord,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
    variant: Variant,
    config: TrainingPhaseConfig,
) -> tuple[PolicyGroup, ...]:
    """The trainer's groups (`training_phase.label_phase_data`: the recorded value estimates, the excluded versions
    dropped) under the variant's reward."""
    estimates = recorded_estimates(record, config.readout)
    excluded = config.excluded_policy_versions
    if variant.transform == Transform.OPEN_CLAIM_PROGRESS_DROPPED:
        tactics = open_claims_only(tactics)
    groups = groups_not_sampled_by(
        policy_groups(record, labels, tactics, estimates, variant.reward).groups, record.expansions, excluded
    )
    if variant.transform != Transform.UNPROVED_CLAIM_EXTRA:
        return groups
    return tuple(
        dataclasses.replace(
            group, samples=tuple(with_unproved_claim_extra(sample, variant.extra) for sample in group.samples)
        )
        for group in groups
    )


def variant_advantages(group: PolicyGroup, variant: Variant, open_claim_edges: frozenset[int]) -> GroupAdvantages:
    advantages = group_advantages(group)
    if variant.transform != Transform.OPEN_CLAIM_NEVER_POSITIVE:
        return advantages
    return dataclasses.replace(
        advantages,
        samples=tuple(
            never_positive(sample_advantages) if sample.edge_ids[0] in open_claim_edges else sample_advantages
            for sample, sample_advantages in zip(group.samples, advantages.samples, strict=True)
        ),
    )


def tree_credit(record: TreeRecord, tokenizer: PolicyTokenizer | None, settings: Settings, band: str) -> TreeCredit:
    """`tokenizer`: None without token credit."""
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, settings.phase_config.reward.off_graph_min_expanded_nodes)
    texts_by_prompt = {(expansion.node_id, expansion.feedback): expansion for expansion in record.expansions}
    opening_by_edge = sample_openings(record, labels, tactics)
    open_claim_edges = {
        edge
        for edge in opening_by_edge
        if any(outcome.leaves_claim_open for outcome in tactics[labels.edges[edge].executed_edge_id])
    }
    token_cache: dict[tuple[int, bool, int], tuple[CompletionTokens, TokenPositions]] = {}
    credit: dict[CreditKey, CreditTally] = {}
    groups_by_variant: dict[str, GroupCount] = {}
    base_signatures: dict[tuple[int, bool], tuple[tuple[int, ...], bool]] = {}
    trained_edges: set[int] = set()
    grouped_edges: set[int] = set()
    mismatches = 0
    production: dict[tuple[int, tuple[int, ...]], tuple[float, ...]] = {}
    for variant, settings_variant in settings.variants.items():
        groups = variant_groups(record, labels, tactics, settings_variant, settings.phase_config)
        if settings.check_production and variant == BASE_VARIANT:
            assert tokenizer is not None
            parts = tree_policy_data(PolicyTree(groups, record.expansions), tokenizer, PolicyDataConfig())
            mismatches = parts.mismatches
            production = {
                (
                    sequence.edge_id,
                    sequence.tokenized.input_ids[sequence.tokenized.prompt_token_count :],
                ): sequence.advantages
                for sequence in parts.sequences
            }
        group_counts = []
        for group in groups:
            advantages = variant_advantages(group, settings_variant, frozenset(open_claim_edges))
            trained = advantages.has_signal(CreditMode.PER_TACTIC)
            group_signature = (signature(advantages), trained)
            if variant == BASE_VARIANT:
                base_signatures[(group.node_id, group.feedback)] = group_signature
                grouped_edges.update(edge for sample in group.samples for edge in sample.edge_ids)
                if trained:
                    trained_edges.update(edge for sample in group.samples for edge in sample.edge_ids)
            base = base_signatures[(group.node_id, group.feedback)]
            group_counts.append(
                GroupCount(
                    groups=1,
                    trained=int(trained),
                    with_bare_have=int(
                        any(opening_by_edge.get(sample.edge_ids[0]) in BARE_OPENINGS for sample in group.samples)
                    ),
                    trained_changed=int(trained != base[1]),
                    sign_changed=int(trained and base[1] and group_signature[0] != base[0]),
                    proof_graph_positive=sum(
                        max(0.0, sample_advantages.sequence or 0.0) * sample.multiplicity
                        for sample, sample_advantages in zip(group.samples, advantages.samples, strict=True)
                        if trained and sample.reaches_proof_graph
                    ),
                )
            )
            if not trained:
                continue
            expansion = texts_by_prompt.get((group.node_id, group.feedback))
            if expansion is None:
                continue
            for sample, sample_advantages in zip(group.samples, advantages.samples, strict=True):
                key = CreditKey(variant, opening_by_edge[sample.edge_ids[0]], sample.reaches_proof_graph, band)
                for completion_index, completion in enumerate(expansion.completions):
                    if completion.edge_id not in sample.edge_ids:
                        continue
                    if tokenizer is None:
                        tally = sequence_only(sample_advantages)
                        credit[key] = added(credit[key], tally) if key in credit else tally
                        continue
                    cache_key = (group.node_id, group.feedback, completion_index)
                    if cache_key not in token_cache:
                        tokens = completion_tokens(tokenizer, completion)
                        token_cache[cache_key] = (
                            tokens,
                            token_positions(tokens, completion, len(sample_advantages.tactics)),
                        )
                    tokens, positions = token_cache[cache_key]
                    spans = completion.tactic_spans if tokens.offsets is not None else ()
                    offsets = tokens.offsets or tuple((0, 0) for _ in tokens.token_ids)
                    credits = token_credits(offsets, spans, tokens.inserted, sample_advantages, CreditMode.PER_TACTIC)
                    if variant == BASE_VARIANT and production:
                        produced = production[(completion.edge_id, tuple(tokens.token_ids))]
                        assert produced == credits.advantages, completion.edge_id
                    first_tactic = sample_advantages.tactics[0] if sample_advantages.tactics else None
                    tally = sequence_tally(
                        len(sample_advantages.tactics),
                        credits.advantages,
                        credits.trained,
                        positions,
                        sample_advantages.sequence,
                        first_tactic,
                    )
                    credit[key] = added(credit[key], tally) if key in credit else tally
        groups_by_variant[variant] = added_all(group_counts, GroupCount())
    samples: dict[SampleKey, SampleCount] = {}
    for label in labels.edges:
        if label.edge_id not in opening_by_edge or record.edges[label.edge_id].feedback:
            continue
        on_graph = (
            any(outcome.label == TacticLabel.PROOF_GRAPH for outcome in tactics[label.executed_edge_id])
            and label.effective_kind.is_forward
        )
        key = SampleKey(opening_by_edge[label.edge_id], on_graph, band)
        count = SampleCount(
            label.sample_count,
            label.sample_count * (label.edge_id in grouped_edges),
            label.sample_count * (label.edge_id in trained_edges),
        )
        samples[key] = added(samples[key], count) if key in samples else count
    return TreeCredit(1, 0, mismatches, credit, samples, groups_by_variant)


WORKER_TOKENIZER: list[PolicyTokenizer] = []


def start_worker(tokenizer: str | None) -> None:
    if tokenizer is not None:
        WORKER_TOKENIZER.append(load_tokenizer(tokenizer))


def file_credit(entry: TreeEntry, directory: Path, settings: Settings) -> TreeCredit:
    try:
        record = read_tree(directory / entry.file)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeCredit(trees=1, unreadable=1)
    tokenizer = WORKER_TOKENIZER[0] if settings.token_credit else None
    return tree_credit(record, tokenizer, settings, proof_band(entry.difficulty))


def sampled_entries(store: TreeStore, phase: int, count: int) -> list[TreeEntry]:
    ordered = sorted(
        store.phase_entries(phase), key=lambda entry: hashlib.sha256(f"{SAMPLE_SEED}\0{entry.file}".encode()).digest()
    )
    present = [entry for entry in ordered if (store.directory / entry.file).exists()]
    return present[:count] if count else present


def as_json(credit: TreeCredit) -> dict[str, object]:
    return {
        "trees": credit.trees,
        "unreadable": credit.unreadable,
        "mismatches": credit.mismatches,
        "credit": [
            {
                "variant": key.variant,
                "opening": key.opening.value,
                "on_graph": key.on_graph,
                "band": key.band,
                **dataclasses.asdict(tally),
            }
            for key, tally in sorted(credit.credit.items())
        ],
        "samples": [
            {"opening": key.opening.value, "on_graph": key.on_graph, "band": key.band, **dataclasses.asdict(count)}
            for key, count in sorted(credit.samples.items())
        ],
        "groups": {variant: dataclasses.asdict(count) for variant, count in credit.groups.items()},
    }


def credit_rows(credit: TreeCredit, variant: str) -> list[str]:
    rows = [
        "| opening | on graph | sequences | sum adv | + / - | per token | explanation (per token) | first tactic "
        "(per token) | `have` token | after first | later tactics | closing | mean score-b | share score-b > 0 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, tally in sorted(credit.credit.items()):
        if key.variant != variant:
            continue
        rows.append(
            f"| {key.opening.value} | {'yes' if key.on_graph else 'no'} | {tally.sequences:,} | {tally.total:+.1f} "
            f"| {tally.positive:.1f} / {tally.negative:.1f} | {tally.total / max(tally.tokens, 1):+.4f} "
            f"| {tally.explanation:+.1f} ({tally.explanation / max(tally.explanation_tokens, 1):+.4f}) "
            f"| {tally.first_tactic:+.1f} ({tally.first_tactic / max(tally.first_tactic_tokens, 1):+.4f}) "
            f"| {tally.first_token:+.2f} | {tally.after_first:+.2f} | {tally.later_tactics:+.1f} "
            f"| {tally.closing:+.2f} "
            f"| {tally.sequence_advantage / tally.sequences:+.3f} | {tally.positive_sequences / tally.sequences:.0%} |"
        )
    return rows


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True, help="the loop's run directory (trees/, training/)")
    parser.add_argument("--trees", type=Path, help="another tree store, labelled with the run's phase configs")
    parser.add_argument("--phases", type=int, nargs="+", required=True)
    parser.add_argument("--config-phase", type=int, help="the run's phase config to use for every phase")
    parser.add_argument("--variants", default="{}", help="JSON: name -> [reward] overrides")
    parser.add_argument("--trees-per-phase", type=int, default=0, help="0: every tree")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--check-production", action="store_true", help="also build the phase's policy data")
    parser.add_argument(
        "--no-token-credit", action="store_true", help="sequence advantages only: no tokenizer, no token placement"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def phase_settings(
    run: Path, phase: int, variants: Mapping[str, Mapping[str, object]], check: bool, token_credit: bool
) -> Settings:
    config = from_json_object(
        TrainingPhaseConfig, tomllib.loads((run / "training" / f"phase_{phase:04d}.toml").read_text(encoding="utf-8"))
    )
    reward = dataclasses.asdict(config.reward)
    built = {BASE_VARIANT: Variant(config.reward)}
    for name, overrides in variants.items():
        changes = dict(overrides)
        transform = Transform(changes.pop("transform", Transform.NONE))
        extra = float(changes.pop("extra", 0.0))
        built[name] = Variant(from_json_object(RewardConfig, reward | changes), transform, extra)
    return Settings(config, built, check, token_credit)


def phase_credit(entries: Sequence[TreeEntry], directory: Path, settings: Settings, pool: Pool | None) -> TreeCredit:
    """In this process without a pool."""
    task = partial(file_credit, directory=directory, settings=settings)
    credit = TreeCredit()
    for tree in map(task, entries) if pool is None else pool.imap_unordered(task, entries, chunksize=2):
        credit = combined(credit, tree)
    return credit


def main() -> None:
    arguments = parse_arguments()
    token_credit = not arguments.no_token_credit
    if arguments.check_production and not token_credit:
        raise ValueError("--check-production compares token advantages: it needs the token credit.")
    store = TreeStore(arguments.trees or arguments.run / "trees")
    variants = json.loads(arguments.variants)
    tokenizer = TOKENIZER if token_credit else None
    results = {}
    pool = None
    if arguments.workers == 1:
        start_worker(tokenizer)
    else:
        pool = Pool(arguments.workers, initializer=start_worker, initargs=(tokenizer,), maxtasksperchild=40)
    with contextlib.ExitStack() as stack:
        if pool is not None:
            stack.enter_context(pool)
        for phase in arguments.phases:
            settings = phase_settings(
                arguments.run, arguments.config_phase or phase, variants, arguments.check_production, token_credit
            )
            entries = sampled_entries(store, phase, arguments.trees_per_phase)
            credit = phase_credit(entries, store.directory, settings, pool)
            results[phase] = as_json(credit)
            print(
                f"\n## Phase {phase}: {credit.trees} trees ({credit.unreadable} unreadable, {credit.mismatches} "
                "token mismatches)\n",
                flush=True,
            )
            for variant in settings.variants:
                print(f"### {variant}: groups {credit.groups[variant]}\n")
                print("\n".join(credit_rows(credit, variant)), flush=True)
            arguments.output.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
