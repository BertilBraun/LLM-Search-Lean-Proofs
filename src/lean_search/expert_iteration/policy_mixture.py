"""Policy SFT mixtures: the search's proof steps plus a token share of traced human steps, in the SFT data format."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from lean_search.expert_iteration.mixing import replay_amount
from lean_search.expert_iteration.proofs import EXPERT_ITERATION_SOURCE
from lean_search.training.sft_data import (
    SftExample,
    SourceStatistics,
    SourceStream,
    TokenizedExample,
    TracedExamples,
    deduplicate,
    ordering_key,
    select_mixture,
    select_validation,
    source_statistics,
)


@dataclass(frozen=True)
class PolicyMixture:
    new: list[TokenizedExample]
    replay: list[TokenizedExample]
    validation: list[TokenizedExample]
    duplicates: int
    over_length: int
    replay_token_budget: int
    replay_sources: tuple[SourceStatistics, ...]
    seed: str

    @property
    def train(self) -> list[TokenizedExample]:
        """New and replayed examples in a fixed pseudo-random order."""
        return sorted([*self.new, *self.replay], key=lambda example: ordering_key(example.example, self.seed))

    @property
    def new_tokens(self) -> int:
        return sum(example.token_count for example in self.new)

    @property
    def replay_tokens(self) -> int:
        return sum(example.token_count for example in self.replay)


def policy_mixture(
    examples: Sequence[SftExample],
    traced: TracedExamples,
    replay_weights: Mapping[str, float],
    replay_fraction: float,
    validation_examples: int,
    validation_seed: str,
    seed: str,
    tokenize: Callable[[SftExample], TokenizedExample | None],
) -> PolicyMixture:
    """Every new example that fits, then traced steps by source weight up to `replay_fraction` of the tokens."""
    new_pool = deduplicate({EXPERT_ITERATION_SOURCE: examples}, seed)
    new_stream = SourceStream(new_pool.examples_by_source[EXPERT_ITERATION_SOURCE], tokenize)
    new_stream.extend_to(math.inf)
    replay_pool = deduplicate(traced.train, seed, excluded_keys=new_pool.keys)
    streams = {source: SourceStream(replay_pool.examples_by_source[source], tokenize) for source in replay_weights}
    budget = replay_amount(new_stream.tokens, replay_fraction)
    # A budget of 0 would make select_mixture take everything.
    if budget:
        select_mixture(streams, replay_weights, budget)
    validation_pool = deduplicate(traced.validation, seed, excluded_keys=new_pool.keys | replay_pool.keys)
    return PolicyMixture(
        new=new_stream.accepted,
        replay=[example for stream in streams.values() for example in stream.accepted],
        validation=select_validation(
            validation_pool.examples_by_source, validation_examples, validation_seed, tokenize
        ),
        duplicates=new_pool.duplicates_by_source[EXPERT_ITERATION_SOURCE],
        over_length=new_stream.over_length,
        replay_token_budget=budget,
        replay_sources=tuple(
            source_statistics(source, traced, replay_pool, streams[source]) for source in replay_weights
        ),
        seed=seed,
    )
