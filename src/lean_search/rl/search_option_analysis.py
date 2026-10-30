"""Stage 0 of the search options' measurement (experiments/search_options_stage0.py), from recorded trees without a
GPU: the policy samples' outcomes and Lean errors, and how often the feedback round would fire.

Every policy sample of a tree counts (infrastructure failures left out), at every node; a held-out tree has only its
root. The feedback round would fire at an expansion with fewer than `min_children` new states from the policy's
samples, a failed block to show and no proof (`policy.expander.feedback_fires`); its cost is estimated as
`sample_count` more samples at the expansion's own generated tokens per sample.
"""

import dataclasses
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.policy.expander import feedback_fires
from lean_search.rl.search_variants import (
    ErrorCategory,
    ErrorCounts,
    SampleOutcome,
    SampleOutcomes,
    error_category,
    rate,
    sample_outcome,
)
from lean_search.search import TreeRecord
from lean_search.search.records import NodeRecord
from lean_search.search.tree import Edge, FailureKind, NodeStatus, StepSource

TRIGGER_THRESHOLDS = (1, 2, 3)


@dataclass(frozen=True)
class ErrorMix:
    trees: int = 0
    outcomes: SampleOutcomes = SampleOutcomes()
    errors: ErrorCounts = ErrorCounts()

    def __add__(self, other: "ErrorMix") -> "ErrorMix":
        return ErrorMix(self.trees + other.trees, self.outcomes + other.outcomes, self.errors + other.errors)


def executed(record: TreeRecord, edge: Edge) -> Edge:
    while edge.repeat_of is not None:
        edge = record.edges[edge.repeat_of]
    return edge


def error_mix(record: TreeRecord) -> ErrorMix:
    outcomes: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    for edge in record.edges:
        ran = executed(record, edge)
        if edge.source != StepSource.POLICY or (ran.failure and ran.failure.kind == FailureKind.REPL_FAILURE):
            continue
        if ran.repaired:
            outcome, error = SampleOutcome.LEAN_ERROR, ErrorCategory.UNKNOWN_IDENTIFIER
        else:
            outcome = sample_outcome(edge.outcome, ran.failure)
            failure = ran.failure
            error = error_category(failure) if outcome == SampleOutcome.LEAN_ERROR and failure is not None else None
        outcomes[outcome.value] += edge.sample_count
        if error is not None:
            errors[error.value] += edge.sample_count
    return ErrorMix(1, SampleOutcomes(**outcomes), ErrorCounts(**errors))


@dataclass(frozen=True)
class FeedbackTriggers:
    """Expansions with policy samples, and those at which the round would fire, per `TRIGGER_THRESHOLDS`."""

    expansions: int = 0
    samples: int = 0
    generated_tokens: int = 0
    fires: tuple[int, ...] = (0,) * len(TRIGGER_THRESHOLDS)
    # The fired expansions' own generated tokens per sample, summed: the round's estimated cost per sample.
    fired_tokens_per_sample: tuple[float, ...] = (0.0,) * len(TRIGGER_THRESHOLDS)

    def __add__(self, other: "FeedbackTriggers") -> "FeedbackTriggers":
        return FeedbackTriggers(
            self.expansions + other.expansions,
            self.samples + other.samples,
            self.generated_tokens + other.generated_tokens,
            tuple(mine + theirs for mine, theirs in zip(self.fires, other.fires, strict=True)),
            tuple(
                mine + theirs
                for mine, theirs in zip(self.fired_tokens_per_sample, other.fired_tokens_per_sample, strict=True)
            ),
        )


def proves(nodes: Sequence[NodeRecord], edge: Edge) -> bool:
    assert edge.target_id is not None
    target = nodes[edge.target_id]
    return not target.goals and target.status != NodeStatus.FAILED


def feedback_triggers(record: TreeRecord) -> FeedbackTriggers:
    """Each expansion as its first request left it (the feedback round's own samples, if any, left out)."""
    by_node: dict[int, list[Edge]] = {}
    for edge in record.edges:
        if not edge.feedback:
            by_node.setdefault(edge.parent_id, []).append(edge)
    totals = FeedbackTriggers()
    for node_id, edges in by_node.items():
        samples = sum(edge.sample_count for edge in edges if edge.source == StepSource.POLICY)
        if not samples:
            continue
        tokens = record.nodes[node_id].expansion_generated_tokens or 0
        fires = tuple(
            feedback_fires(edges, threshold, lambda edge: proves(record.nodes, edge))
            for threshold in TRIGGER_THRESHOLDS
        )
        per_sample = tokens / samples
        totals += FeedbackTriggers(
            1, samples, tokens, tuple(map(int, fires)), tuple(per_sample if fired else 0.0 for fired in fires)
        )
    return totals


@dataclass(frozen=True)
class TriggerRow:
    min_children: int
    share: float
    # Extra generated tokens of `sample_count` more samples at every fired expansion, against all generated tokens.
    extra_token_share: float


def trigger_rows(triggers: FeedbackTriggers, sample_count: int) -> list[TriggerRow]:
    return [
        TriggerRow(
            threshold,
            rate(triggers.fires[index], triggers.expansions),
            rate(sample_count * triggers.fired_tokens_per_sample[index], triggers.generated_tokens),
        )
        for index, threshold in enumerate(TRIGGER_THRESHOLDS)
    ]


def shares(mix: ErrorMix) -> dict[str, float]:
    """Outcomes and error categories as shares of the samples."""
    samples = mix.outcomes.total
    counts = {**dataclasses.asdict(mix.outcomes), **dataclasses.asdict(mix.errors)}
    return {name: rate(count, samples) for name, count in counts.items()}


def mix_table(rows: Sequence[tuple[str, ErrorMix]]) -> str:
    names = [
        *(item.name for item in dataclasses.fields(SampleOutcomes)),
        *(item.name for item in dataclasses.fields(ErrorCounts)),
    ]
    lines = ["| | trees | samples | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 3)]
    for label, mix in rows:
        values = shares(mix)
        cells = " | ".join(f"{values[name]:.3f}" for name in names)
        lines.append(f"| {label} | {mix.trees} | {mix.outcomes.total} | {cells} |")
    return "\n".join(lines) + "\n"


def trigger_table(rows: Sequence[tuple[str, FeedbackTriggers]], sample_count: int) -> str:
    columns = [f"fires at min_children {threshold} (extra tokens)" for threshold in TRIGGER_THRESHOLDS]
    lines = ["| | expansions | " + " | ".join(columns) + " |", "|" + "---|" * (len(columns) + 2)]
    for label, triggers in rows:
        cells = " | ".join(
            f"{row.share:.3f} ({row.extra_token_share:+.3f})" for row in trigger_rows(triggers, sample_count)
        )
        lines.append(f"| {label} | {triggers.expansions} | {cells} |")
    return "\n".join(lines) + "\n"
