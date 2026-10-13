"""Prompt states for single-step reasoning: traced train-split steps with the later states of their reference proof."""

import hashlib
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.corpora.records import DataSplit, TracedStep
from lean_search.corpora.tracing import stable_fraction
from lean_search.lean import normalize_goal

type GoalKey = tuple[str, ...]


@dataclass(frozen=True)
class ReasoningState:
    identifier: str
    step: TracedStep
    # The goals after each later step of the same traced proof; the last entry is empty (proved).
    later_goals: tuple[tuple[str, ...], ...]
    # The same goals are a prompt of the policy's SFT data.
    seen_in_sft: bool

    @property
    def source(self) -> str:
        return self.step.source

    @property
    def goals(self) -> tuple[str, ...]:
        return self.step.goals_before

    @property
    def reference_goal_keys(self) -> tuple[GoalKey, ...]:
        """The reference next state first, then the states further along the reference proof."""
        return tuple(goal_key(goals) for goals in (self.step.goals_after, *self.later_goals))


class TracedSource(StrEnum):
    # The merged snapshot (steps_<split>.jsonl) the SFT data was built from.
    SNAPSHOT = "snapshot"
    # Every finished tracing shard, including those traced after the snapshot.
    SHARDS = "shards"


@dataclass(frozen=True)
class StateSelectionConfig:
    count: int = 16_000
    states_per_proof: int = 2
    max_goal_characters: int = 3000
    seed: str = "reasoning"
    # SFT data sets (names under $LEAN_SEARCH_DATA/sft) whose prompts mark a state as seen; recorded, not avoided,
    # since the unseen states of sources the SFT data used whole are the ones whose reference step was too long.
    seen_sft_data: tuple[str, ...] = ()
    # Earlier reasoning runs whose states are skipped, so a later round prompts on fresh states.
    excluded_runs: tuple[str, ...] = ()
    split: DataSplit = DataSplit.TRAIN
    traced: TracedSource = TracedSource.SNAPSHOT
    # Empty takes every source.
    sources: tuple[str, ...] = ()
    # Only states whose goals are not prompts of `seen_sft_data`.
    unseen_only: bool = False


def goal_key(goals: Sequence[str]) -> GoalKey:
    return tuple(normalize_goal(goal) for goal in goals)


def goals_digest(goals: Sequence[str]) -> bytes:
    return hashlib.sha256("\0".join(goal_key(goals)).encode()).digest()


def step_identifier(step: TracedStep) -> str:
    return f"{step.proof_identifier}#{step.step_index}"


def proof_states(steps: Sequence[TracedStep], seen_goals: Collection[bytes] = frozenset()) -> list[ReasoningState]:
    ordered = sorted(steps, key=lambda step: step.step_index)
    return [
        ReasoningState(
            step_identifier(step),
            step,
            tuple(later.goals_after for later in ordered[index + 1 :]),
            goals_digest(step.goals_before) in seen_goals,
        )
        for index, step in enumerate(ordered)
    ]


def without_seen_states(states: Iterable[ReasoningState], seen_goals: Collection[bytes]) -> list[ReasoningState]:
    return [state for state in states if goals_digest(state.goals) not in seen_goals]


def round_robin[T](sequences: Sequence[Sequence[T]]) -> list[T]:
    # Equal shares while every sequence lasts; the exhausted ones leave the rest to the others.
    longest = max((len(sequence) for sequence in sequences), default=0)
    return [sequence[index] for index in range(longest) for sequence in sequences if index < len(sequence)]


def select_states(
    steps: Iterable[TracedStep],
    config: StateSelectionConfig,
    seen_goals: Collection[bytes] = frozenset(),
    excluded_identifiers: Collection[str] = frozenset(),
) -> list[ReasoningState]:
    """At most `states_per_proof` states per proof of the split, sources interleaved, in a fixed pseudo-random order."""
    steps_by_proof: dict[str, list[TracedStep]] = defaultdict(list)
    for step in steps:
        if step.split == config.split and (not config.sources or step.source in config.sources):
            steps_by_proof[step.proof_identifier].append(step)
    states_by_source: dict[str, list[ReasoningState]] = defaultdict(list)
    for proof_steps in steps_by_proof.values():
        candidates = [
            state
            for state in proof_states(proof_steps, seen_goals)
            if len("\n\n".join(state.goals)) <= config.max_goal_characters
            and state.identifier not in excluded_identifiers
            and not (config.unseen_only and state.seen_in_sft)
        ]
        candidates.sort(key=lambda state: stable_fraction(state.identifier, config.seed))
        states_by_source[proof_steps[0].source].extend(candidates[: config.states_per_proof])
    ordered_sources = [
        sorted(states_by_source[source], key=lambda state: stable_fraction(state.identifier, f"{config.seed} order"))
        for source in sorted(states_by_source)
    ]
    return round_robin(ordered_sources)[: config.count]
