import math

import httpx
import pytest

from lean_search.policy import ChatMessage, PolicyClient

LEAN_PROMPT = "theorem add_comm_example (a b : Nat) : a + b = b + a := by\n  "


async def test_generate_returns_one_sample_per_requested_sample(policy_client: PolicyClient) -> None:
    generation = await policy_client.generate(LEAN_PROMPT, sample_count=4, max_tokens=8)
    assert len(generation.samples) == 4


async def test_ignore_eos_generates_exactly_max_tokens(policy_client: PolicyClient) -> None:
    generation = await policy_client.generate(LEAN_PROMPT, sample_count=3, max_tokens=8, ignore_eos=True)
    assert [sample.token_count for sample in generation.samples] == [8, 8, 8]


async def test_completion_token_count_is_sum_over_samples(policy_client: PolicyClient) -> None:
    generation = await policy_client.generate(LEAN_PROMPT, sample_count=4, max_tokens=16, stop=["\n"])
    assert generation.completion_token_count == sum(sample.token_count for sample in generation.samples)


async def test_stop_string_is_not_part_of_the_text(policy_client: PolicyClient) -> None:
    generation = await policy_client.generate(LEAN_PROMPT, sample_count=8, max_tokens=32, stop=["\n"])
    assert not any("\n" in sample.text for sample in generation.samples)


async def test_cumulative_logprob_is_negative(policy_client: PolicyClient) -> None:
    generation = await policy_client.generate(LEAN_PROMPT, sample_count=4, max_tokens=8, ignore_eos=True)
    assert all(sample.cumulative_logprob < 0 for sample in generation.samples)


async def test_greedy_generation_is_deterministic(policy_client: PolicyClient) -> None:
    first = await policy_client.generate(LEAN_PROMPT, sample_count=1, max_tokens=12, temperature=0.0)
    second = await policy_client.generate(LEAN_PROMPT, sample_count=1, max_tokens=12, temperature=0.0)
    assert first.samples[0].text == second.samples[0].text


async def test_same_seed_reproduces_samples(policy_client: PolicyClient) -> None:
    first = await policy_client.generate(LEAN_PROMPT, sample_count=2, max_tokens=12, seed=7)
    second = await policy_client.generate(LEAN_PROMPT, sample_count=2, max_tokens=12, seed=7)
    assert [sample.text for sample in first.samples] == [sample.text for sample in second.samples]


async def test_repeated_prompt_hits_the_prefix_cache(policy_client: PolicyClient) -> None:
    long_prompt = "-- Lean 4 proof state\n" + "".join(f"h{index} : x{index} ≤ x{index + 1}\n" for index in range(400))
    await policy_client.generate(long_prompt, sample_count=1, max_tokens=1)
    generation = await policy_client.generate(long_prompt, sample_count=1, max_tokens=1)
    assert generation.cached_prompt_token_count > 0


@pytest.mark.parametrize("enable_thinking", [False, True])
async def test_chat_generation_returns_requested_sample_count(
    policy_client: PolicyClient, enable_thinking: bool
) -> None:
    messages = [ChatMessage(role="user", content=f"Give the next Lean 4 tactic for:\n{LEAN_PROMPT}")]
    generation = await policy_client.generate_chat(
        messages, enable_thinking=enable_thinking, sample_count=2, max_tokens=16
    )
    assert len(generation.samples) == 2


async def test_chat_without_thinking_does_not_open_a_think_block(policy_client: PolicyClient) -> None:
    messages = [ChatMessage(role="user", content=f"Give the next Lean 4 tactic for:\n{LEAN_PROMPT}")]
    generation = await policy_client.generate_chat(messages, enable_thinking=False, sample_count=4, max_tokens=48)
    assert not any("<think>" in sample.text for sample in generation.samples)


async def test_score_next_token_returns_top_k_tokens(policy_client: PolicyClient) -> None:
    distribution = await policy_client.score_next_token("Remaining proof steps: ", top_k=5)
    assert len(distribution.logprob_by_token_id) == 5


async def test_score_next_token_probabilities_sum_to_at_most_one(policy_client: PolicyClient) -> None:
    distribution = await policy_client.score_next_token("Remaining proof steps: ", top_k=20)
    assert sum(math.exp(logprob) for logprob in distribution.logprob_by_token_id.values()) <= 1.0 + 1e-3


async def test_unknown_adapter_is_rejected(policy_client: PolicyClient) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        await policy_client.generate(LEAN_PROMPT, sample_count=1, max_tokens=4, adapter="no-such-adapter")
