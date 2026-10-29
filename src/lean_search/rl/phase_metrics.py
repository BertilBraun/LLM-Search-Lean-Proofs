"""The search family of a phase from its trees: graph statistics plus failure tiers, forced answers and loops.

Failure tiers follow the error analysis (DESIGN.md, "Lean execution and harness") per policy sample, from the failure
kind and Lean's message, approximately: `malformed` is a sample without a usable block, a forbidden step, a parse error
or an unknown constant in Lean's message; `invalid_in_state` is the identifier check's rejection (it mixes unknown
hypothesis names with unknown constants) and ill-typed terms; `timeout` are heartbeat and wall-clock limits; every
other Lean error is `valid_but_failing`. Infrastructure failures count in none.
"""

import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.monitoring.families import FailureTiers, SearchPhase
from lean_search.rl.tree_statistics import GraphStatistics
from lean_search.search.records import TreeRecord
from lean_search.search.texts import SampledCompletion
from lean_search.search.tree import Edge, Failure, FailureKind, StepSource

MALFORMED_MESSAGES = re.compile(r"unexpected token|unexpected identifier|expected|unknown constant|unknown identifier")
INVALID_MESSAGES = re.compile(
    r"type mismatch|application type mismatch|failed to synthesize|function expected|invalid field|"
    r"unknown (?:free variable|hypothesis)|ambiguous|invalid argument"
)
UNKNOWN_NAME_MESSAGES = re.compile(r"unknown identifier|unknown constant|unknown free variable")
# A forced answer repeats itself when one of its segments (lines or sentences this long) occurs this often.
REPEATED_SEGMENT_CHARACTERS = 16
REPEATED_SEGMENT_COUNT = 3
SEGMENT_SEPARATOR = re.compile(r"\n|(?<=[.!?])\s+")


class FailureTier(StrEnum):
    MALFORMED = "malformed"
    INVALID_IN_STATE = "invalid_in_state"
    VALID_BUT_FAILING = "valid_but_failing"
    TIMEOUT = "timeout"


def failure_tier(failure: Failure) -> FailureTier | None:
    match failure.kind:
        case FailureKind.UNPARSED | FailureKind.FORBIDDEN:
            return FailureTier.MALFORMED
        case FailureKind.UNKNOWN_IDENTIFIER:
            return FailureTier.INVALID_IN_STATE
        case FailureKind.HEARTBEAT_TIMEOUT | FailureKind.WALL_CLOCK_TIMEOUT:
            return FailureTier.TIMEOUT
        case FailureKind.REPL_FAILURE:
            return None
        case FailureKind.ERROR:
            message = failure.message.lower()
            if INVALID_MESSAGES.search(message):
                return FailureTier.INVALID_IN_STATE
            if MALFORMED_MESSAGES.search(message):
                return FailureTier.MALFORMED
            return FailureTier.VALID_BUT_FAILING


def executed_edge(record: TreeRecord, edge: Edge) -> Edge:
    return edge if edge.repeat_of is None else record.edges[edge.repeat_of]


def policy_edges(records: Sequence[TreeRecord]) -> Iterator[tuple[TreeRecord, Edge]]:
    for record in records:
        for edge in record.edges:
            if edge.source == StepSource.POLICY:
                yield record, edge


def failure_tiers(records: Sequence[TreeRecord]) -> FailureTiers:
    counts: Counter[FailureTier] = Counter()
    for record, edge in policy_edges(records):
        failure = executed_edge(record, edge).failure
        tier = None if failure is None else failure_tier(failure)
        if tier is not None:
            counts[tier] += edge.sample_count
    return FailureTiers(**{tier.value: count for tier, count in counts.items()})


@dataclass(frozen=True)
class UnknownNames:
    """Policy samples that refer to a name that does not exist (the naming A/B's error rate)."""

    samples: int
    unknown: int

    @property
    def rate(self) -> float:
        return self.unknown / self.samples if self.samples else 0.0


def refers_to_unknown_name(failure: Failure | None) -> bool:
    if failure is None:
        return False
    match failure.kind:
        case FailureKind.UNKNOWN_IDENTIFIER:
            return True
        case FailureKind.ERROR:
            return UNKNOWN_NAME_MESSAGES.search(failure.message.lower()) is not None
        case _:
            return False


def unknown_names(records: Sequence[TreeRecord]) -> UnknownNames:
    """Per policy sample (infrastructure failures left out): the identifier check's rejections, Lean's unknown names."""
    samples = 0
    unknown = 0
    for record, edge in policy_edges(records):
        failure = executed_edge(record, edge).failure
        if failure is not None and failure.kind == FailureKind.REPL_FAILURE:
            continue
        samples += edge.sample_count
        unknown += edge.sample_count * refers_to_unknown_name(failure)
    return UnknownNames(samples, unknown)


def is_forced(completion: SampledCompletion) -> bool:
    return bool(completion.tokens.inserted)


def repeats_itself(text: str) -> bool:
    segments = Counter(
        segment.strip()
        for segment in SEGMENT_SEPARATOR.split(text)
        if len(segment.strip()) >= REPEATED_SEGMENT_CHARACTERS
    )
    return any(count >= REPEATED_SEGMENT_COUNT for count in segments.values())


def forced_completions(records: Sequence[TreeRecord]) -> list[SampledCompletion]:
    return [
        completion
        for record in records
        for expansion in record.expansions
        for completion in expansion.completions
        if is_forced(completion)
    ]


def mean_block_tactics(records: Sequence[TreeRecord]) -> float:
    """Top-level tactics per executed policy sample (after flattening), weighted by the samples behind each edge."""
    tactics = 0
    samples = 0
    for record, edge in policy_edges(records):
        executed = executed_edge(record, edge)
        if executed.total_tactics:
            tactics += executed.total_tactics * edge.sample_count
            samples += edge.sample_count
    return tactics / samples if samples else 0.0


def search_phase_record(records: Sequence[TreeRecord], statistics: GraphStatistics) -> SearchPhase:
    expansions = sum(record.result.accounting.expansions for record in records)
    lean_seconds = sum(record.result.accounting.lean_seconds for record in records)
    forced = forced_completions(records)
    return SearchPhase(
        graph=statistics,
        failure_tiers=failure_tiers(records),
        expansions=expansions,
        lean_seconds=lean_seconds,
        lean_seconds_per_expansion=lean_seconds / expansions if expansions else 0.0,
        forced_answers=len(forced),
        repetition_loops=sum(repeats_itself(completion.text) for completion in forced),
        mean_block_tactics=mean_block_tactics(records),
    )
