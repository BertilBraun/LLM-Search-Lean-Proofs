"""Thinking mode in the loop: the reasoning behind every policy step, kept so that training can learn it.

The search's tree keeps only the tactic blocks. With `policy.thinking`, the search service's ReasoningExpander
(thinking_expander.py) keeps, per expanded node and block, the reasoning of the most likely sample that wrote the
block; it is stored next to the tree, and the digests attach it to the preference pairs, which then train in thinking
format.
"""

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search import TreeRecord
from lean_search.search.records import from_json_object, to_json


@dataclass(frozen=True)
class StepReasoning:
    # The expanded node and the block as the search received it (an edge's text).
    node_id: int
    step: str
    reasoning: str


def write_reasoning(path: Path, reasoning: Sequence[StepReasoning]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.writelines(to_json(item) + "\n" for item in reasoning)


def read_reasoning(path: Path) -> list[StepReasoning]:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return [from_json_object(StepReasoning, json.loads(line)) for line in file if line.strip()]


def edge_reasoning(record: TreeRecord, reasoning: Sequence[StepReasoning]) -> Mapping[int, str]:
    """The reasoning behind each edge of the tree that has one, by edge id."""
    by_step = {(item.node_id, normalize_tactic_block(item.step)): item.reasoning for item in reasoning}
    return {
        edge.edge_id: by_step[key]
        for edge in record.edges
        if (key := (edge.parent_id, normalize_tactic_block(edge.text))) in by_step
    }
