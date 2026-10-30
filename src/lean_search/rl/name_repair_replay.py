"""Name repair replayed offline (experiments/name_repair_replay.py): recorded policy blocks that failed on unknown
dotted names, repaired at several difflib thresholds and run again in Lean from their recorded parent state.

The parent state is rebuilt from the tree's recorded steps (start, then each step's block on the path), checked
against the recorded goals. A threshold's repair either has no candidate (some name has no constant of its namespace
that close), repeats what a lower threshold already ran, or runs: valid (the block completes), partial (a prefix ran)
or failed.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from lean_search.lean import LeanRepl, ProofState
from lean_search.lean.identifiers import NameRepairer, unknown_names
from lean_search.lean.plans import plan_block
from lean_search.rl.search_variants import rate
from lean_search.search import TreeRecord
from lean_search.search.tree import FailureKind, StepSource

BUILD_HEARTBEATS = 200_000
BUILD_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class UnknownNameFailure:
    problem_name: str
    node_id: int
    edge_id: int
    text: str
    # The dotted unknown names (only those can be repaired) and every unknown name the failure named.
    dotted: tuple[str, ...]
    names: tuple[str, ...]


def unknown_name_failures(record: TreeRecord) -> list[UnknownNameFailure]:
    """The tree's distinct policy blocks that failed on unknown names with at least one of them dotted."""
    failures = []
    for edge in record.edges:
        failure = edge.failure
        if edge.source != StepSource.POLICY or edge.repeat_of is not None or edge.repaired or failure is None:
            continue
        if failure.kind not in (FailureKind.UNKNOWN_IDENTIFIER, FailureKind.ERROR):
            continue
        names = unknown_names(failure.message)
        dotted = tuple(name for name in names if "." in name.removeprefix("_root_."))
        if dotted:
            failures.append(
                UnknownNameFailure(record.problem_name, edge.parent_id, edge.edge_id, edge.text, dotted, names)
            )
    return failures


class ReplayOutcome(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class ReplayRun:
    outcome: ReplayOutcome
    lean_seconds: float


class StateBuilder:
    """A tree's recorded states rebuilt on one REPL, each once."""

    def __init__(self, repl: LeanRepl, record: TreeRecord, header: str) -> None:
        self.repl = repl
        self.record = record
        self.header = header
        self.states: dict[int, ProofState | None] = {}

    async def state(self, node_id: int) -> ProofState | None:
        if node_id not in self.states:
            self.states[node_id] = await self._build(node_id)
        return self.states[node_id]

    async def _build(self, node_id: int) -> ProofState | None:
        node = self.record.nodes[node_id]
        if node.parent_id is None:
            start = await self.repl.start_proof(self.record.statement, self.header)
            state = start.outcome if isinstance(start.outcome, ProofState) else None
        else:
            parent = await self.state(node.parent_id)
            if parent is None or node.step is None:
                return None
            result = await self.repl.apply_block(parent, node.step, BUILD_HEARTBEATS, BUILD_TIMEOUT_SECONDS)
            state = result.state if result.failure is None else None
        if state is None or normalized(state.goals) != normalized(node.goals):
            return None
        return state


def normalized(goals: Sequence[str]) -> list[str]:
    return [" ".join(goal.split()) for goal in goals]


async def replay_block(
    repl: LeanRepl, state: ProofState, text: str, heartbeats: int, timeout_seconds: float
) -> ReplayRun:
    result = await repl.apply_block(state, plan_block(text), heartbeats, timeout_seconds)
    if result.failure is None:
        outcome = ReplayOutcome.VALID
    else:
        outcome = ReplayOutcome.PARTIAL if result.applied_tactics else ReplayOutcome.FAILED
    return ReplayRun(outcome, result.elapsed_seconds)


@dataclass(frozen=True)
class FailureReplay:
    """One failure's repairs: per threshold the repaired text (None: no candidate), and each distinct text's run."""

    failure: UnknownNameFailure
    replayable: bool
    texts: tuple[str | None, ...]
    runs: dict[str, ReplayRun] = field(default_factory=dict)


def repaired_texts(
    failure: UnknownNameFailure, repairers: Sequence[NameRepairer], namespaces: Sequence[str]
) -> tuple[str | None, ...]:
    texts = []
    for repairer in repairers:
        repaired = repairer.repaired(failure.text, failure.names, namespaces)
        texts.append(None if repaired is None else repaired.text)
    return tuple(texts)


@dataclass(frozen=True)
class ThresholdSummary:
    min_similarity: float
    failures: int
    # A repair found for every unknown name; of those, the replayed ones by outcome.
    repaired: int
    valid: int
    partial: int
    failed: int
    # Of all failures: the share a repair made valid.
    valid_share: float
    # Lean seconds of the repaired runs, per failure.
    lean_seconds_per_failure: float


def threshold_summaries(replays: Sequence[FailureReplay], thresholds: Sequence[float]) -> list[ThresholdSummary]:
    """Over the replayable failures (their parent state rebuilt)."""
    replayable = [replay for replay in replays if replay.replayable]
    summaries = []
    for index, threshold in enumerate(thresholds):
        runs = [replay.runs[text] for replay in replayable if (text := replay.texts[index]) is not None]
        counts = {outcome: sum(run.outcome == outcome for run in runs) for outcome in ReplayOutcome}
        summaries.append(
            ThresholdSummary(
                min_similarity=threshold,
                failures=len(replayable),
                repaired=len(runs),
                valid=counts[ReplayOutcome.VALID],
                partial=counts[ReplayOutcome.PARTIAL],
                failed=counts[ReplayOutcome.FAILED],
                valid_share=rate(counts[ReplayOutcome.VALID], len(replayable)),
                lean_seconds_per_failure=rate(sum(run.lean_seconds for run in runs), len(replayable)),
            )
        )
    return summaries


def summary_table(summaries: Sequence[ThresholdSummary]) -> str:
    names = [item.name for item in dataclasses.fields(ThresholdSummary)]
    lines = ["| " + " | ".join(names) + " |", "|" + "---|" * len(names)]
    for summary in summaries:
        values = [f"{value:.3f}" if isinstance(value, float) else str(value) for value in dataclasses.astuple(summary)]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"
