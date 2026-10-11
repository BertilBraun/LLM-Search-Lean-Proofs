"""The value model as A*'s batch value estimator: one prefill-only request per node, read from the bin tokens."""

import asyncio
import contextlib
import itertools
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from lean_search.policy.client import NextTokenDistribution, PolicyClient
from lean_search.policy.expander import load_tokenizer, served_max_model_length
from lean_search.search.priority import ValueEstimates
from lean_search.search.tree import Node
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, BinDistribution, bin_distribution
from lean_search.value.config import ValueConfig
from lean_search.value.prompts import ValueTokenizer, bin_token_ids, render_value_prompt

# A state too long for the server's context cannot be expanded by the policy either.
TOO_LONG_DISTRIBUTION = tuple(float(index == DEAD_BIN) for index in range(BIN_COUNT))


@dataclass(frozen=True)
class BinnedValueEstimates(ValueEstimates):
    # Per node, the probabilities of the bins 1..7, 8+, dead.
    distributions: tuple[tuple[float, ...], ...] = ()


@dataclass(frozen=True)
class StateScore:
    probabilities: tuple[float, ...]
    prompt_tokens: int


@dataclass
class ValueStatistics:
    requests: int = 0
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    prompts_too_long: int = 0
    # Bin tokens outside the returned top-k logprobs, summed over requests.
    missing_bin_tokens: int = 0
    request_seconds: float = 0.0

    def record(self, distribution: NextTokenDistribution, bins: BinDistribution, seconds: float) -> None:
        self.requests += 1
        self.prompt_tokens += distribution.prompt_token_count
        self.cached_prompt_tokens += distribution.cached_prompt_token_count
        self.missing_bin_tokens += bins.missing_bin_tokens
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

    async def estimate(self, nodes: Sequence[Node]) -> BinnedValueEstimates:
        scores = await asyncio.gather(*(self.score(node.goals) for node in nodes))
        return BinnedValueEstimates(
            remaining_steps=tuple(self.config.readout.remaining_steps(score.probabilities) for score in scores),
            prompt_tokens=sum(score.prompt_tokens for score in scores),
            distributions=tuple(score.probabilities for score in scores),
        )

    async def score(self, goals: Sequence[str]) -> StateScore:
        prompt = render_value_prompt(self.tokenizer, goals)
        if len(self.tokenizer.encode(prompt, add_special_tokens=False)) >= self.max_model_length:
            self.statistics.prompts_too_long += 1
            return StateScore(TOO_LONG_DISTRIBUTION, 0)
        started = time.monotonic()
        distribution = await next(self._clients).score_next_token(
            prompt, top_k=self.config.top_k, adapter=self.config.adapter
        )
        bins = bin_distribution(distribution.logprob_by_token_id, self.bin_token_ids)
        self.statistics.record(distribution, bins, time.monotonic() - started)
        return StateScore(bins.probabilities, distribution.prompt_token_count)


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
