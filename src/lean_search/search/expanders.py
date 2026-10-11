"""Expanders propose candidate steps for a node; the search executes them batch by batch."""

import contextlib
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Protocol

from lean_search.data import Problem
from lean_search.lean import LeanRepl
from lean_search.search.tree import Node, SearchTree, StepSource

DEFAULT_AUTOMATION_TACTICS = (
    "decide",
    "omega",
    "positivity",
    "intros",
    "constructor",
    "rfl",
    "tauto",
    "simp",
    "field_simp",
    "norm_num",
    "linarith",
    "ring_nf",
    "simp_all",
    "nlinarith",
    "aesop",
)


@dataclass(frozen=True)
class Candidate:
    text: str
    source: StepSource
    log_probability: float | None = None
    # Token counts are summed over candidates, so a prompt shared by n samples is counted on one candidate only.
    prompt_tokens: int = 0
    generated_tokens: int = 0
    heartbeats: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class SearchContext:
    problem: Problem
    tree: SearchTree
    repl: LeanRepl


type CandidateBatches = AsyncGenerator[Sequence[Candidate], None]


class Expander(Protocol):
    """Yields batches of candidates; the search runs each batch before asking for the next and stops at a proof."""

    def expand(self, node: Node, context: SearchContext) -> CandidateBatches: ...


@dataclass(frozen=True)
class AutomationConfig:
    tactics: tuple[str, ...] = DEFAULT_AUTOMATION_TACTICS
    heartbeats: int | None = None
    timeout_seconds: float | None = None
    # Wall-clock kills cost a process restart and a replay, and a tactic that hung once tends to hang on the
    # descendants too; 0 never disables a tactic.
    max_wall_clock_timeouts_per_tactic: int = 1


class AutomationExpander:
    def __init__(self, config: AutomationConfig) -> None:
        self.config = config

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield [
            Candidate(
                tactic,
                StepSource.AUTOMATION,
                heartbeats=self.config.heartbeats,
                timeout_seconds=self.config.timeout_seconds,
            )
            for tactic in self.config.tactics
            if not self._disabled(tactic, context.tree)
        ]

    def _disabled(self, tactic: str, tree: SearchTree) -> bool:
        limit = self.config.max_wall_clock_timeouts_per_tactic
        return limit > 0 and tree.wall_clock_timeouts(tactic) >= limit


class CompositeExpander:
    """Runs its expanders in order, e.g. the automation sweep first so that a closing tactic saves the policy call."""

    def __init__(self, expanders: Sequence[Expander]) -> None:
        self.expanders = tuple(expanders)

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        for expander in self.expanders:
            async with contextlib.aclosing(expander.expand(node, context)) as batches:
                async for batch in batches:
                    yield batch
