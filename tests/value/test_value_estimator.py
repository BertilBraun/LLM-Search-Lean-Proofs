import math
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from value_trees import TreeBuilder

from lean_search.search import AStar, PriorityKind
from lean_search.search.config import parse_run_config
from lean_search.value.bins import Readout
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import (
    TOO_LONG_DISTRIBUTION,
    ValueModelEstimator,
    bin_distribution,
    open_value_estimator,
)

POLICY_URL = os.environ.get("LEAN_SEARCH_POLICY_URL", "http://127.0.0.1:8000/v1")
VALUE_SECTION = """
[priority]
kind = "a_star"
value_weight = 0.5

[value]
model = "qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
adapter = "value-v0"

[value.readout]
dead_steps = 24.0
"""


def test_bins_are_renormalized_over_the_bin_tokens() -> None:
    logprobs = {1: math.log(0.3), 2: math.log(0.1), 3: math.log(0.2), 99: math.log(0.4)}
    assert bin_distribution(logprobs, (1, 2, 3)).probabilities == pytest.approx((0.5, 1 / 6, 1 / 3))


def test_a_bin_outside_the_top_k_gets_the_smallest_returned_logprob() -> None:
    logprobs = {1: math.log(0.5), 2: math.log(0.25), 99: math.log(0.125)}
    assert bin_distribution(logprobs, (1, 2, 3)).probabilities == pytest.approx((4 / 7, 2 / 7, 1 / 7))


def test_bins_outside_the_top_k_are_counted() -> None:
    logprobs = {1: math.log(0.5), 99: math.log(0.125)}
    assert bin_distribution(logprobs, (1, 2, 3)).missing_bin_tokens == 2


def test_a_state_too_long_for_the_server_reads_out_as_a_dead_end() -> None:
    assert Readout(dead_steps=16.0).remaining_steps(TOO_LONG_DISTRIBUTION) == 16.0


def test_value_section_is_parsed() -> None:
    config = parse_run_config(VALUE_SECTION)
    assert (config.priority.kind, config.value.adapter, config.value.readout) == (
        PriorityKind.A_STAR,
        "value-v0",
        Readout(eight_or_more_steps=12.0, dead_steps=24.0),
    )


def test_runs_without_a_value_section_have_no_value_model() -> None:
    assert parse_run_config("").value.model == ""


@pytest.mark.parametrize(
    "text",
    [
        VALUE_SECTION.replace('kind = "a_star"', 'kind = "cumulative_log_probability"'),
        VALUE_SECTION.replace('tokenizer = "Qwen/Qwen3.5-2B"\n', ""),
        VALUE_SECTION + "top_k = 0\n",
    ],
)
def test_invalid_value_section_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(text)


@pytest.fixture
async def served_estimator() -> AsyncIterator[ValueModelEstimator]:
    try:
        response = httpx.get(f"{POLICY_URL}/models", timeout=5.0)
    except httpx.TransportError:
        pytest.skip(f"no vLLM server at {POLICY_URL} (set LEAN_SEARCH_POLICY_URL)")
    base = next(model for model in response.json()["data"] if model["parent"] is None)
    config = ValueConfig(model=base["id"], tokenizer=base["root"], server_urls=(POLICY_URL, POLICY_URL))
    async with open_value_estimator(config) as estimator:
        yield estimator


async def test_served_estimates_are_distributions_over_the_bins(served_estimator: ValueModelEstimator) -> None:
    builder = TreeBuilder("x : ℕ\n⊢ x + 0 = x")
    child = builder.child(builder.root, "a b : ℝ\nh₀ : a + b = 3\n⊢ a = 3 - b")
    estimates = await served_estimator.estimate([builder.root, child])
    assert [sum(distribution) for distribution in estimates.distributions] == pytest.approx([1.0, 1.0])


async def test_a_star_takes_h_from_the_served_value_model(served_estimator: ValueModelEstimator) -> None:
    builder = TreeBuilder("x : ℕ\n⊢ x + 0 = x")
    child = builder.child(builder.root, "x : ℕ\n⊢ x = x")
    scores = await AStar(served_estimator, value_weight=1.0).score([child], builder.tree)
    assert scores.priorities == (1.0 + scores.value_estimates[0],)
