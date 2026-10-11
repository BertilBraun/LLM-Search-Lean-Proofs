"""Value labels: exact remaining steps, censored lower bounds and dead ends, from traced proofs and search trees."""

import dataclasses
import json
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.records import TracedStep
from lean_search.lean.text import normalize_goal
from lean_search.search.records import TreeRecord
from lean_search.search.tree import NodeStatus
from lean_search.value.bins import STEP_BIN_COUNT, step_bin


class LabelKind(StrEnum):
    EXACT = "exact"
    # Censored: at least `steps` more steps, possibly a dead end.
    AT_LEAST = "at_least"
    DEAD = "dead"


@dataclass(frozen=True)
class ValueExample:
    goals: tuple[str, ...]
    kind: LabelKind
    # The exact remaining steps, the censored lower bound, or 0 for a dead end.
    steps: int
    weight: float
    source: str
    identifier: str
    depth: int

    @property
    def goal_key(self) -> tuple[str, ...]:
        return tuple(normalize_goal(goal) for goal in self.goals)


@dataclass(frozen=True)
class TreeLabelConfig:
    at_least_weight: float = 1.0
    # A dead end only means that this search expanded everything below the state without a proof.
    dead_weight: float = 0.5


@dataclass(frozen=True)
class LabelCounts:
    examples: int
    exact: int
    at_least: int
    dead: int
    # Per step bin 1..7, 8+.
    exact_bins: tuple[int, ...]
    at_least_bins: tuple[int, ...]


def traced_examples(steps: Iterable[TracedStep]) -> list[ValueExample]:
    return [
        ValueExample(
            step.goals_before,
            LabelKind.EXACT,
            step.remaining_steps,
            1.0,
            step.source,
            step.proof_identifier,
            step.step_index,
        )
        for step in steps
    ]


def predecessors(record: TreeRecord) -> dict[int, list[int]]:
    """Child and duplicate edges, reversed; a duplicate edge leads to the existing node with the same goals."""
    by_target: dict[int, list[int]] = {}
    for edge in record.edges:
        if edge.target_id is not None:
            by_target.setdefault(edge.target_id, []).append(edge.parent_id)
    return by_target


def distances_to(targets: Iterable[int], by_target: Mapping[int, Sequence[int]]) -> dict[int, int]:
    """The fewest edges from every node that reaches one of the targets."""
    distances = dict.fromkeys(targets, 0)
    queue = deque(distances)
    while queue:
        node_id = queue.popleft()
        for predecessor in by_target.get(node_id, ()):
            if predecessor not in distances:
                distances[predecessor] = distances[node_id] + 1
                queue.append(predecessor)
    return distances


def frontier_ids(record: TreeRecord) -> set[int]:
    """Nodes not fully tried: open ones and those with an attempt lost to an infrastructure failure."""
    frontier = {node.node_id for node in record.nodes if node.status == NodeStatus.OPEN}
    frontier.update(
        edge.parent_id for edge in record.edges if edge.failure is not None and not edge.failure.is_negative_label
    )
    return frontier


def tree_examples(record: TreeRecord, source: str, config: TreeLabelConfig) -> list[ValueExample]:
    """Nodes reaching the proof: exact distance; nodes reaching the frontier: at least 1 + distance; others: dead."""
    by_target = predecessors(record)
    proof_ids = [node.node_id for node in record.nodes if node.status == NodeStatus.PROVED and not node.goals]
    to_proof = distances_to(proof_ids, by_target)
    to_frontier = distances_to(frontier_ids(record), by_target)
    examples = []
    for node in record.nodes:
        # Proved states, including those whose verification failed, need no estimate.
        if not node.goals:
            continue
        if node.node_id in to_proof:
            kind, steps, weight = LabelKind.EXACT, to_proof[node.node_id], 1.0
        elif node.node_id in to_frontier:
            kind, steps, weight = LabelKind.AT_LEAST, 1 + to_frontier[node.node_id], config.at_least_weight
        else:
            assert node.status == NodeStatus.FAILED, (record.problem_name, node.node_id, node.status)
            kind, steps, weight = LabelKind.DEAD, 0, config.dead_weight
        examples.append(ValueExample(node.goals, kind, steps, weight, source, record.problem_name, node.depth))
    return examples


def label_group(example: ValueExample) -> str:
    match example.kind:
        case LabelKind.EXACT if example.steps >= STEP_BIN_COUNT:
            return f"exact {STEP_BIN_COUNT}+"
        case LabelKind.EXACT:
            return f"exact {example.steps}"
        case LabelKind.AT_LEAST if example.steps == 1:
            return "at least 1 (open)"
        case LabelKind.AT_LEAST:
            return "at least 2+"
        case LabelKind.DEAD:
            return "dead"


LABEL_GROUPS = (
    *(f"exact {steps}" for steps in range(1, STEP_BIN_COUNT)),
    f"exact {STEP_BIN_COUNT}+",
    "dead",
    "at least 2+",
    "at least 1 (open)",
)


def merge_rank(example: ValueExample) -> tuple[int, int]:
    match example.kind:
        case LabelKind.EXACT:
            return 0, example.steps
        case LabelKind.DEAD:
            return 1, 0
        case LabelKind.AT_LEAST:
            return 2, -example.steps


def merge_duplicates(examples: Iterable[ValueExample]) -> list[ValueExample]:
    """One example per normalized goal list: the fewest exact steps, else dead, else the largest lower bound."""
    best: dict[tuple[str, ...], ValueExample] = {}
    for example in examples:
        key = example.goal_key
        current = best.get(key)
        if current is None or merge_rank(example) < merge_rank(current):
            best[key] = example
    return list(best.values())


def label_counts(examples: Sequence[ValueExample]) -> LabelCounts:
    exact_bins = [0] * STEP_BIN_COUNT
    at_least_bins = [0] * STEP_BIN_COUNT
    for example in examples:
        match example.kind:
            case LabelKind.EXACT:
                exact_bins[step_bin(example.steps)] += 1
            case LabelKind.AT_LEAST:
                at_least_bins[step_bin(example.steps)] += 1
            case LabelKind.DEAD:
                pass
    return LabelCounts(
        examples=len(examples),
        exact=sum(exact_bins),
        at_least=sum(at_least_bins),
        dead=sum(example.kind == LabelKind.DEAD for example in examples),
        exact_bins=tuple(exact_bins),
        at_least_bins=tuple(at_least_bins),
    )


def write_examples(path: Path, examples: Iterable[ValueExample]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def read_examples(path: Path) -> Iterator[ValueExample]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            yield ValueExample(**fields | {"goals": tuple(fields["goals"]), "kind": LabelKind(fields["kind"])})
