"""Thinking mode in the loop: the reasoning behind every policy step, kept so that training can learn it.

The search's tree keeps only the tactic blocks. With `policy.thinking`, the search service's ReasoningExpander
(thinking_expander.py) keeps, per expanded node and block, the reasoning of the most likely sample that wrote the
block; it is stored next to the tree (with the statement's header), and the digests attach it to the preference
pairs, which then train in thinking format. For each proof-step pair with reasoning the digests also keep a
ThinkingContext, the proof state before the step and the reference states after it, so that a training phase can
shorten the reasoning and check that the shorter version still leads the policy to a working step.
"""

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search import TreeRecord
from lean_search.search.records import from_json_object, to_json
from lean_search.training.dpo_data import PreferencePair


@dataclass(frozen=True)
class StepReasoning:
    # The expanded node and the block as the search received it (an edge's text).
    node_id: int
    step: str
    reasoning: str


@dataclass(frozen=True)
class CompressionConfig:
    """Shortening long reasoning before training (the reasoning module's rewrite and sufficiency check)."""

    # Reasoning up to this many tokens stays as it is.
    min_tokens: int = 300
    target_tokens: int = 150
    max_accepted_tokens: int = 200
    min_accepted_tokens: int = 0
    # Above 0, rewrites condense to this fraction of the original, keeping every step, and are accepted between the
    # two ratios of its length (the reasoning agent's round-2 rule); rewrite_max_tokens bounds a rewrite's sample.
    target_ratio: float = 0.0
    min_accepted_ratio: float = 0.0
    max_accepted_ratio: float = 1.0
    rewrite_max_tokens: int = 320
    candidates: int = 2
    # The rewriting model is the served base model (None) or an adapter of it, without thinking.
    rewriter_adapter: str | None = None
    # Policy samples given a shortened reasoning; one working step makes it sufficient.
    sufficiency_samples: int = 4
    sufficiency_max_tokens: int = 512
    lean_processes: int = 8
    requests_in_flight: int = 64


@dataclass(frozen=True)
class TreeReasoning:
    # The statement's header, to rebuild proof states of the tree.
    header: str
    steps: tuple[StepReasoning, ...]


@dataclass(frozen=True)
class ThinkingContext:
    """Where a proof-step pair's reasoning applies: the state before the step and the proof's states after it."""

    pair_key: str
    header: str
    statement: str
    # The proof's steps before this one, which rebuild the state.
    previous_steps: tuple[str, ...]
    goals: tuple[str, ...]
    reference_goals: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ThinkingItem:
    pair: PreferencePair
    context: ThinkingContext


def write_reasoning(path: Path, reasoning: TreeReasoning) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write(to_json(reasoning))


def read_reasoning(path: Path) -> TreeReasoning:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return from_json_object(TreeReasoning, json.load(file))


def edge_reasoning(record: TreeRecord, reasoning: Sequence[StepReasoning]) -> Mapping[int, str]:
    """The reasoning behind each edge of the tree that has one, by edge id."""
    by_step = {(item.node_id, normalize_tactic_block(item.step)): item.reasoning for item in reasoning}
    return {
        edge.edge_id: by_step[key]
        for edge in record.edges
        if (key := (edge.parent_id, normalize_tactic_block(edge.text))) in by_step
    }
