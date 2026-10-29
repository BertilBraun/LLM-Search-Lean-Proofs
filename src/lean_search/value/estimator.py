"""The value model as A*'s batch value estimator: one prefill-only request per node, read from the bin tokens."""

import asyncio
import contextlib
import itertools
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

from lean_search.policy.client import NextTokenDistributions, PolicyClient
from lean_search.policy.expander import load_tokenizer, served_max_model_length
from lean_search.search.priority import ValueEstimates
from lean_search.search.tree import Node
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, BinDistribution, bin_distribution
from lean_search.value.config import ValueConfig
from lean_search.value.prompts import ValueTokenizer, bin_token_ids, render_value_prompt

TRANSPORT_ATTEMPTS = 3
# States per scoring request: large enough to spread the client's per-request cost, small enough to use both servers.
STATES_PER_REQUEST = 32
# A state too long for the server's context cannot be expanded by the policy either.
TOO_LONG_DISTRIBUTION = tuple(float(index == DEAD_BIN) for index in range(BIN_COUNT))


@dataclass(frozen=True)
class StateScore:
    probabilities: tuple[float, ...]
    prompt_tokens: int


@dataclass(frozen=True)
class ScoredStates:
    # Per state, the probabilities of the bins 1..7, 8+, dead.
    states: tuple[tuple[float, ...], ...]
    prompt_tokens: int


@dataclass
class ValueStatistics:
    # Scored states; several share one HTTP request (http_requests).
    requests: int = 0
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    prompts_too_long: int = 0
    # Bin tokens outside the returned top-k logprobs, summed over states.
    missing_bin_tokens: int = 0
    transport_retries: int = 0
    request_seconds: float = 0.0
    http_requests: int = 0

    def record(self, scored: NextTokenDistributions, bins: Sequence[BinDistribution], seconds: float) -> None:
        self.requests += len(bins)
        self.http_requests += 1
        self.prompt_tokens += scored.prompt_token_count
        self.cached_prompt_tokens += scored.cached_prompt_token_count
        self.missing_bin_tokens += sum(state.missing_bin_tokens for state in bins)
        self.request_seconds += seconds


class ValueModelEstimator:
    def __init__(
        self, config: ValueConfig, tokenizer: ValueTokenizer, clients: Sequence[PolicyClient], max_model_length: int
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self.max_model_length = max_model_length
        self.bin_token_ids = bin_token_ids(tokenizer)
        self.statistics = ValueStatistics()
        self._clients = itertools.cycle(clients)

    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        scored = await self.score_states([node.goals for node in nodes])
        return ValueEstimates(
            remaining_steps=tuple(
                self.config.readout.remaining_steps(probabilities) for probabilities in scored.states
            ),
            prompt_tokens=scored.prompt_tokens,
            distributions=scored.states,
        )

    async def score(self, goals: Sequence[str]) -> StateScore:
        scored = await self.score_states([goals])
        return StateScore(scored.states[0], scored.prompt_tokens)

    async def score_states(self, states: Sequence[Sequence[str]]) -> ScoredStates:
        """Bin probabilities per state, scored STATES_PER_REQUEST at a time, and the prompt tokens of all."""
        prompts = [render_value_prompt(self.tokenizer, goals) for goals in states]
        fitting = [
            index
            for index, prompt in enumerate(prompts)
            if len(self.tokenizer.encode(prompt, add_special_tokens=False)) < self.max_model_length
        ]
        self.statistics.prompts_too_long += len(prompts) - len(fitting)
        chunks = [fitting[start : start + STATES_PER_REQUEST] for start in range(0, len(fitting), STATES_PER_REQUEST)]
        results = await asyncio.gather(*(self.score_prompts([prompts[index] for index in chunk]) for chunk in chunks))
        probabilities = [TOO_LONG_DISTRIBUTION] * len(states)
        for chunk, (chunk_probabilities, _) in zip(chunks, results, strict=True):
            for index, state_probabilities in zip(chunk, chunk_probabilities, strict=True):
                probabilities[index] = state_probabilities
        return ScoredStates(tuple(probabilities), sum(prompt_tokens for _, prompt_tokens in results))

    async def score_prompts(self, prompts: Sequence[str]) -> tuple[list[tuple[float, ...]], int]:
        started = time.monotonic()
        scored = await self.next_token_distributions(prompts)
        bins = [bin_distribution(logprobs, self.bin_token_ids) for logprobs in scored.logprobs_by_token_id]
        self.statistics.record(scored, bins, time.monotonic() - started)
        return [state.probabilities for state in bins], scored.prompt_token_count

    async def next_token_distributions(self, prompts: Sequence[str]) -> NextTokenDistributions:
        # Scoring is idempotent; under load the server sometimes closes a kept-alive connection mid-request.
        for _ in range(TRANSPORT_ATTEMPTS - 1):
            try:
                return await self.request(prompts)
            except httpx.TransportError:
                self.statistics.transport_retries += 1
        return await self.request(prompts)

    async def request(self, prompts: Sequence[str]) -> NextTokenDistributions:
        client = next(self._clients)
        return await client.score_next_tokens(prompts, top_k=self.config.top_k, adapter=self.config.adapter)


@contextlib.asynccontextmanager
async def open_value_estimator(config: ValueConfig) -> AsyncIterator[ValueModelEstimator]:
    tokenizer = load_tokenizer(config.tokenizer)
    max_model_length = min([await served_max_model_length(url, config.model) for url in config.server_urls])
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(url, config.model, timeout_seconds=config.request_timeout_seconds)
            )
            for url in config.server_urls
        ]
        yield ValueModelEstimator(config, tokenizer, clients, max_model_length)
