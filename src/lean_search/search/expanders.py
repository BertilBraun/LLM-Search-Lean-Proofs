"""Expanders propose candidate steps for a node; the search executes them batch by batch."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lean_search.data import Problem
from lean_search.lean import LeanRepl
from lean_search.search.texts import GeneratedText, UnparsedSample
from lean_search.search.tree import Node, SearchTree, StepSource

DEFAULT_AUTOMATION_TACTICS = (
    "decide",
    "omega",
    "intros",
    "constructor",
    "rfl",
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
    # Logged on the edge, never charged: the prompt the candidate was sampled from and the samples that produced it.
    prompt_tokens: int = 0
    generated_tokens: int = 0
    heartbeats: int | None = None
    timeout_seconds: float | None = None
    # Written after the policy's thoughts were cut off and closed (budget forcing).
    forced: bool = False
    # The policy samples that produced this text.
    sample_count: int = 1
    # Those samples' generated texts (empty for automation and for callers that do not keep them).
    completions: tuple[GeneratedText, ...] = ()


@dataclass(frozen=True)
class CandidateBatch:
    """The candidates of one request and the tokens it cost, charged on arrival whether or not the candidates run."""

    candidates: tuple[Candidate, ...]
    prompt_tokens: int = 0
    generated_tokens: int = 0
    # The policy's prompt and its samples without a usable block (recorded as failed edges).
    prompt: str = ""
    unparsed: tuple[UnparsedSample, ...] = ()
    # The policy's sampling settings, recorded with the samples' log-probabilities.
    temperature: float | None = None
    top_p: float | None = None


@dataclass(frozen=True)
class SearchContext:
    problem: Problem
    tree: SearchTree
    repl: LeanRepl
    # Batches an expander had already paid for when the search stopped early; the search charges and clears them.
    abandoned_batches: list[CandidateBatch] = field(default_factory=list)


type CandidateBatches = AsyncGenerator[CandidateBatch, None]


class Expander(Protocol):
    """Yields batches; the search charges each, runs its candidates before asking for the next and stops at a proof."""

    def expand(self, node: Node, context: SearchContext) -> CandidateBatches: ...


@dataclass(frozen=True)
class AutomationConfig:
    tactics: tuple[str, ...] = DEFAULT_AUTOMATION_TACTICS
    # Lean's maxHeartbeats units; the sweep keeps Lean's default limit.
    heartbeats: int | None = 200_000
    # None: the search's emergency wall-clock stop.
    timeout_seconds: float | None = None
    # Wall-clock kills cost a process restart and a replay, and a tactic that hung once tends to hang on the
    # descendants too; 0 never disables a tactic.
    max_wall_clock_timeouts_per_tactic: int = 1
    # A sweep tactic that ran out of heartbeats once tends to on the descendants too; 0 never disables a tactic.
    max_heartbeat_timeouts_per_tactic: int = 1


class AutomationExpander:
    def __init__(self, config: AutomationConfig) -> None:
        self.config = config

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(
            tuple(
                Candidate(
                    tactic,
                    StepSource.AUTOMATION,
                    heartbeats=self.config.heartbeats,
                    timeout_seconds=self.config.timeout_seconds,
                )
                for tactic in self.config.tactics
                if not self._disabled(tactic, context.tree)
            )
        )

    def _disabled(self, tactic: str, tree: SearchTree) -> bool:
        wall_clock_limit = self.config.max_wall_clock_timeouts_per_tactic
        heartbeat_limit = self.config.max_heartbeat_timeouts_per_tactic
        return (wall_clock_limit > 0 and tree.wall_clock_timeouts(tactic) >= wall_clock_limit) or (
            heartbeat_limit > 0 and tree.heartbeat_timeouts(tactic) >= heartbeat_limit
        )


class CompositeExpander:
    """Runs its expanders in order; with `overlap` the later ones start at once and their batches wait their turn."""

    def __init__(self, expanders: Sequence[Expander], overlap: bool = False) -> None:
        self.expanders = tuple(expanders)
        self.overlap = overlap

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        if not self.overlap:
            for expander in self.expanders:
                async with contextlib.aclosing(expander.expand(node, context)) as batches:
                    async for batch in batches:
                        yield batch
            return
        first, *later = self.expanders
        prefetches = [asyncio.create_task(collect_batches(expander.expand(node, context))) for expander in later]
        unconsumed: list[CandidateBatch] = []
        next_prefetch = 0
        try:
            async with contextlib.aclosing(first.expand(node, context)) as batches:
                async for batch in batches:
                    yield batch
            while next_prefetch < len(prefetches):
                unconsumed = await prefetches[next_prefetch]
                next_prefetch += 1
                while unconsumed:
                    yield unconsumed.pop(0)
        except GeneratorExit:
            if asyncio.current_task().cancelling():
                cancel_all(prefetches[next_prefetch:])
                raise
            # The search stopped early (a proof): requests already sent are still paid for.
            context.abandoned_batches.extend(unconsumed)
            for prefetch in prefetches[next_prefetch:]:
                context.abandoned_batches.extend(await prefetch)
            raise
        except BaseException:
            cancel_all(prefetches[next_prefetch:])
            raise


async def collect_batches(batches: CandidateBatches) -> list[CandidateBatch]:
    async with contextlib.aclosing(batches):
        return [batch async for batch in batches]


def cancel_all(tasks: Sequence[asyncio.Task[list[CandidateBatch]]]) -> None:
    for task in tasks:
        task.cancel()
