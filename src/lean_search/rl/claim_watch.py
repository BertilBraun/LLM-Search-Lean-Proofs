"""The claim habits a GRPO arm is watched on per phase (review BG, S1, after arm A's bare-`have` drift): the policy's
block openings by what their claim became, where they train and with what advantage, from a phase's trees under the
phase's own reward, beside the loop's health records (`experiments/claim_watch.py`;
`experiments/analysis/bare_have_credit.py` replays the same classes at token level)."""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from lean_search.monitoring.families import HealthMeasurements, PhaseHealth
from lean_search.rl.advantages import group_advantages
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.fixed_sets import character_stratum
from lean_search.rl.grpo_groups import policy_groups
from lean_search.rl.health_checks import HeldOutRates, held_out_rates, read_health_history
from lean_search.rl.training_phase import TrainingPhaseConfig, groups_not_sampled_by
from lean_search.rl.tree_summary import is_bare_have, is_linarith_opening, is_proof_have, opening
from lean_search.search.graph_labels import GraphLabels, label_graph
from lean_search.search.records import TreeRecord, from_json_object
from lean_search.search.tactic_labels import CLAIM_TACTIC, TacticLabel, TacticOutcome, policy_tactics
from lean_search.search.tree import StepSource
from lean_search.value.graph_targets import recorded_estimates

# Probe v2's bands of the shortest known proof's characters (`FixedSetConfig.edges`); the curriculum's difficulty is
# those characters / 100.
PROOF_BAND_EDGES = (500, 1000, 1500, 2000, 3000, 4500)
UNKNOWN_BAND = "unknown"


class Opening(StrEnum):
    """A block's first top-level tactic as `tree_summary.block_habits` counts it; a bare `have` by what its claim
    became."""

    BARE_CLOSED_IN_BLOCK = "bare have, proved in its block"
    BARE_OPEN_ON_GRAPH = "bare have, open, on the proof graph"
    BARE_OPEN_PROVED_ELSEWHERE = "bare have, open, proved by the tree off the graph"
    BARE_OPEN_ALONE = "bare have, open, never proved, nothing after"
    BARE_OPEN_FAILED_ATTEMPT = "bare have, open, never proved, a failing tactic after"
    BARE_OPEN_CONTINUED = "bare have, open, never proved, valid tactics after"
    BARE_WASTED = "bare have, no progress or redundant"
    BARE_FAILING = "bare have, failing itself"
    PROOF_HAVE = "have ... := (inline proof)"
    OBTAIN = "obtain opening"
    SUFFICES = "suffices opening"
    OTHER_CLAIM = "other claim opening (replace, ...)"
    LINARITH = "linarith / nlinarith opening"
    OTHER = "other opening"


BARE_OPENINGS = tuple(item for item in Opening if item.name.startswith("BARE"))
# On the proof graph: decompositions proving their claim in the block, and the openings stating no claim.
DECOMPOSITIONS = (Opening.BARE_CLOSED_IN_BLOCK, Opening.PROOF_HAVE)
DIRECT_OPENINGS = (Opening.LINARITH, Opening.OTHER)


def opening_of(text: str, outcomes: Sequence[TacticOutcome]) -> Opening:
    """`text`: the executed block; `outcomes`: its tactics' (`policy_tactics`)."""
    first_tactic = opening(text)
    if is_proof_have(first_tactic):
        return Opening.PROOF_HAVE
    if not is_bare_have(first_tactic):
        match CLAIM_TACTIC.search(first_tactic):
            case None:
                return Opening.LINARITH if is_linarith_opening(first_tactic) else Opening.OTHER
            case found if found[1] == "obtain":
                return Opening.OBTAIN
            case found if found[1] == "suffices":
                return Opening.SUFFICES
            case _:
                return Opening.OTHER_CLAIM
    first = outcomes[0]
    later = [outcome.label for outcome in outcomes[1:]]
    match first.label:
        case TacticLabel.FAILING:
            return Opening.BARE_FAILING
        case TacticLabel.NO_PROGRESS | TacticLabel.REDUNDANT_HYPOTHESIS:
            return Opening.BARE_WASTED
        case _ if not first.leaves_claim_open:
            return Opening.BARE_CLOSED_IN_BLOCK
        case TacticLabel.UNPROVED_CLAIM if TacticLabel.FAILING in later:
            return Opening.BARE_OPEN_FAILED_ATTEMPT
        case TacticLabel.UNPROVED_CLAIM:
            return Opening.BARE_OPEN_CONTINUED if later else Opening.BARE_OPEN_ALONE
        case TacticLabel.PROOF_GRAPH:
            return Opening.BARE_OPEN_ON_GRAPH
        case _:
            return Opening.BARE_OPEN_PROVED_ELSEWHERE


def proof_band(difficulty: float | None) -> str:
    """The probe band of a statement from its curriculum difficulty (`TreeEntry.difficulty`)."""
    if difficulty is None:
        return UNKNOWN_BAND
    return character_stratum(round(difficulty * 100), PROOF_BAND_EDGES)


def sample_openings(
    record: TreeRecord, labels: GraphLabels, tactics: Mapping[int, Sequence[TacticOutcome]]
) -> dict[int, Opening]:
    """Per policy edge (repeats included) its executed block's opening."""
    return {
        label.edge_id: opening_of(record.edges[label.executed_edge_id].text, tactics[label.executed_edge_id])
        for label in labels.edges
        if label.source == StepSource.POLICY and label.executed_edge_id in tactics
    }


class WatchKey(NamedTuple):
    opening: Opening
    # The sample reaches the proof graph (`GroupSample.reaches_proof_graph`).
    on_graph: bool
    band: str


@dataclass(frozen=True)
class AdvantageSum:
    """Over the trained sequences of a key: one per policy sample, each with its sample's score minus baseline."""

    sequences: int = 0
    advantage: float = 0.0

    def __add__(self, other: "AdvantageSum") -> "AdvantageSum":
        return AdvantageSum(self.sequences + other.sequences, self.advantage + other.advantage)

    @property
    def mean(self) -> float | None:
        return self.advantage / self.sequences if self.sequences else None


@dataclass(frozen=True)
class TreeWatch:
    trees: int = 0
    # First-round policy samples by key; their per-sequence advantages in the groups the trainer keeps.
    samples: dict[WatchKey, int] = field(default_factory=dict)
    advantages: dict[WatchKey, AdvantageSum] = field(default_factory=dict)

    def __add__(self, other: "TreeWatch") -> "TreeWatch":
        samples = dict(self.samples)
        for key, count in other.samples.items():
            samples[key] = samples.get(key, 0) + count
        advantages = dict(self.advantages)
        for key, total in other.advantages.items():
            advantages[key] = advantages.get(key, AdvantageSum()) + total
        return TreeWatch(self.trees + other.trees, samples, advantages)

    def share(self, openings: Iterable[Opening], on_graph: bool | None = None) -> float | None:
        """Of all first-round samples, those opening as `openings` (and on or off the proof graph when given)."""
        chosen = set(openings)
        total = sum(self.samples.values())
        part = sum(
            count
            for key, count in self.samples.items()
            if key.opening in chosen and (on_graph is None or key.on_graph == on_graph)
        )
        return part / total if total else None

    def advantage(
        self, openings: Iterable[Opening], on_graph: bool | None = None, band: str | None = None
    ) -> AdvantageSum:
        chosen = set(openings)
        found = AdvantageSum()
        for key, total in self.advantages.items():
            if key.opening in chosen and on_graph in (None, key.on_graph) and band in (None, key.band):
                found += total
        return found


def tree_watch(record: TreeRecord, config: TrainingPhaseConfig, band: str) -> TreeWatch:
    """The trainer's groups (recorded value estimates, excluded versions dropped, `has_signal` under the phase's
    credit) with every sample's sequence advantage, and the tree's first-round samples, by opening."""
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, config.reward.off_graph_min_expanded_nodes)
    openings = sample_openings(record, labels, tactics)
    estimates = recorded_estimates(record, config.readout)
    groups = groups_not_sampled_by(
        policy_groups(record, labels, tactics, estimates, config.reward).groups,
        record.expansions,
        config.excluded_policy_versions,
    )
    advantages: dict[WatchKey, AdvantageSum] = {}
    for group in groups:
        found = group_advantages(group)
        if not found.has_signal(config.credit):
            continue
        for sample, sample_advantages in zip(group.samples, found.samples, strict=True):
            if sample_advantages.sequence is None:
                continue
            key = WatchKey(openings[sample.edge_ids[0]], sample.reaches_proof_graph, band)
            total = AdvantageSum(sample.multiplicity, sample_advantages.sequence * sample.multiplicity)
            advantages[key] = advantages.get(key, AdvantageSum()) + total
    samples: dict[WatchKey, int] = {}
    for label in labels.edges:
        if label.edge_id not in openings or record.edges[label.edge_id].feedback:
            continue
        on_graph = label.effective_kind.is_forward and any(
            outcome.label == TacticLabel.PROOF_GRAPH for outcome in tactics[label.executed_edge_id]
        )
        key = WatchKey(openings[label.edge_id], on_graph, band)
        samples[key] = samples.get(key, 0) + label.sample_count
    return TreeWatch(1, samples, advantages)


def version_zero_held_out(path: Path) -> HeldOutRates | None:
    """Version 0's held-out states from a run's evaluations.jsonl, the last written."""
    if not path.exists():
        return None
    found = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            summary = from_json_object(EvaluationSummary, json.loads(line))
            if summary.kind == EvaluationKind.HELD_OUT_STATES and summary.policy_version == 0:
                found = held_out_rates(summary)
    return found


@dataclass(frozen=True)
class PhaseWatch:
    phase: int
    trees: TreeWatch
    # The phase's health record (`health.jsonl`), when the phase closed.
    health: HealthMeasurements | None


def phase_health(run_directory: Path, phase: int) -> HealthMeasurements | None:
    records: Mapping[int, PhaseHealth] = {
        record.phase: record for record in read_health_history(run_directory / "health.jsonl")
    }
    return records[phase].measured if phase in records else None


# The stop rule review BG suggested for arm A's rerun; the owner decides.
MAX_BARE_HAVE_RISE = 0.05
MAX_SUBCLASS_GROWTH = 1.5


class Subclass(NamedTuple):
    name: str
    openings: tuple[Opening, ...]
    # Only samples on (True) or off (False) the proof graph; None: both.
    on_graph: bool | None


# The two that grew in arm A's first run.
GROWING_SUBCLASSES = (
    Subclass("bare have proved in its block, off the proof graph", (Opening.BARE_CLOSED_IN_BLOCK,), False),
    Subclass("bare have left open, a failing attempt after", (Opening.BARE_OPEN_FAILED_ATTEMPT,), None),
)


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.3f}"


def ratio(value: float | None, reference: float | None) -> float | None:
    return None if value is None or not reference else value / reference


def times(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}x"


def premium(trees: TreeWatch) -> tuple[float | None, float | None]:
    """Per-sample advantage of on-graph decompositions and of on-graph direct openings."""
    return trees.advantage(DECOMPOSITIONS, on_graph=True).mean, trees.advantage(DIRECT_OPENINGS, on_graph=True).mean


def watch_lines(current: PhaseWatch, reference: PhaseWatch, version_zero: HeldOutRates | None) -> list[str]:
    """The watch list of phase `current` against the reference phase (the run's first)."""
    now, then = current.health, reference.health
    lines = [f"Claim watch, phase {current.phase} ({current.trees.trees} trees) against phase {reference.phase}:"]
    bare, bare_before = (None if health is None else health.bare_have_share for health in (now, then))
    below, below_before = (None if health is None else health.below_band_bare_have_share for health in (now, then))
    rise = None if bare is None or bare_before is None else bare - bare_before
    flag = " STOP-RULE" if rise is not None and rise > MAX_BARE_HAVE_RISE else ""
    lines.append(
        f"- bare `have` openings: {percent(bare)} of the blocks ({percent(below)} below the band); phase "
        f"{reference.phase} {percent(bare_before)} ({percent(below_before)}); rise "
        f"{'-' if rise is None else f'{100 * rise:+.1f} points'} (suggested stop: > {100 * MAX_BARE_HAVE_RISE:.0f}"
        f" points by phase 4){flag}"
    )
    for subclass in GROWING_SUBCLASSES:
        share, share_before = (
            watch.trees.share(subclass.openings, subclass.on_graph) for watch in (current, reference)
        )
        growth = ratio(share, share_before)
        flag = " STOP-RULE" if growth is not None and growth > MAX_SUBCLASS_GROWTH else ""
        lines.append(
            f"- {subclass.name}: {percent(share)} of the samples; phase {reference.phase} {percent(share_before)}; "
            f"{times(growth)} (suggested stop: > {MAX_SUBCLASS_GROWTH:g}x){flag}"
        )
    substitutes = ", ".join(
        f"{name} {percent(current.trees.share((item,)))} ({percent(reference.trees.share((item,)))})"
        for name, item in (
            ("obtain", Opening.OBTAIN),
            ("suffices", Opening.SUFFICES),
            ("have … :=", Opening.PROOF_HAVE),
        )
    )
    lines.append(f"- substitutes, of the samples (phase {reference.phase}): {substitutes}")
    proved, proved_before = (None if health is None else health.claim_proved_rate for health in (now, then))
    lines.append(f"- claims proved of those bare haves leave open: {percent(proved)} ({percent(proved_before)})")
    decompositions, direct = premium(current.trees)
    decompositions_before, direct_before = premium(reference.trees)
    bare_class = current.trees.advantage(BARE_OPENINGS)
    lines.append(
        f"- on the proof graph, per sample: decompositions {signed(decompositions)}, direct openings {signed(direct)} "
        f"({times(ratio(decompositions, direct))}); phase {reference.phase} {signed(decompositions_before)}, "
        f"{signed(direct_before)} ({times(ratio(decompositions_before, direct_before))}); bare `have` openings "
        f"{signed(bare_class.mean)} per sample, {bare_class.advantage:+.1f} summed over {bare_class.sequences:,}"
    )
    tokens, tokens_before = (None if health is None else health.mean_explanation_tokens for health in (now, then))
    lines.append(
        f"- mean explanation tokens: {'-' if tokens is None else f'{tokens:.0f}'} "
        f"({'-' if tokens_before is None else f'{tokens_before:.0f}'})"
    )
    valid = None if now is None else now.held_out_valid_rate
    success = None if now is None else now.held_out_success
    lines.append(
        f"- held-out after the phase: valid Lean {percent(valid)}, success {percent(success)}; v0 "
        f"{percent(None if version_zero is None else version_zero.valid_rate)}, "
        f"{percent(None if version_zero is None else version_zero.success)}"
    )
    return lines
