import os
from collections.abc import AsyncIterator
from typing import Protocol

import pytest

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl, ProofState
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyExpander, PolicyTokenizer, load_tokenizer, open_policy_expander
from lean_search.policy.prompts import assistant_message, prompt_messages, render_completion, render_prompt
from lean_search.search import Candidate, CandidateBatch, SearchContext, SearchTree, StepSource

POLICY_URL = os.environ.get("LEAN_SEARCH_POLICY_URL", "http://127.0.0.1:8000/v1")
CANDIDATE_MODELS = (
    "Qwen/Qwen3.5-2B",
    "Qwen/Qwen3.5-2B-Base",
    "Qwen/Qwen3-1.7B",
    "Qwen/Qwen2.5-Math-1.5B-Instruct",
    "Qwen/Qwen2.5-Math-1.5B",
)
GOALS = ("a b : ℝ\nh₀ : a + b = 3\nh₁ : a - b = 1\n⊢ a = 2",)
SAMPLE_COUNT = 8


class ServedModel(Protocol):
    name: str
    repository: str


def cached_tokenizer(repository: str) -> PolicyTokenizer:
    try:
        return load_tokenizer(repository)
    except OSError:
        pytest.skip(f"{repository} is not in the Hugging Face cache")


@pytest.mark.parametrize("repository", CANDIDATE_MODELS)
@pytest.mark.parametrize("few_shot", [False, True])
def test_prompt_and_completion_are_the_rendered_conversation(repository: str, few_shot: bool) -> None:
    tokenizer = cached_tokenizer(repository)
    block = "nlinarith [sq_nonneg (a - b)]\nlinarith"
    messages = prompt_messages(GOALS, few_shot=few_shot)
    conversation = [{"role": message.role, "content": message.content} for message in messages]
    conversation.append({"role": "assistant", "content": assistant_message(block)})
    rendered = tokenizer.apply_chat_template(conversation, tokenize=False, enable_thinking=False)
    assert render_prompt(tokenizer, GOALS, few_shot=few_shot) + render_completion(block) + "\n" == rendered


@pytest.fixture
async def policy_expander(served_model: ServedModel) -> AsyncIterator[PolicyExpander]:
    config = PolicyConfig(
        model=served_model.name,
        tokenizer=served_model.repository,
        server_urls=(POLICY_URL, POLICY_URL),
        sample_count=SAMPLE_COUNT,
        max_tokens=96,
    )
    async with open_policy_expander(config) as expander:
        yield expander


async def expand_root(expander: PolicyExpander) -> list[CandidateBatch]:
    state = ProofState("", "theorem probe (a b : ℝ) : a = 2 := by", (), GOALS, 0, 0)
    tree = SearchTree("probe", state, 0.0)
    problem = Problem("probe", Split.VALID, "", state.statement, "", GOALS[0])
    context = SearchContext(problem, tree, LeanRepl())
    return [batch async for batch in expander.expand(tree.root, context)]


async def root_candidates(expander: PolicyExpander) -> list[Candidate]:
    return [candidate for batch in await expand_root(expander) for candidate in batch.candidates]


async def test_expansion_yields_distinct_policy_candidates(policy_expander: PolicyExpander) -> None:
    candidates = await root_candidates(policy_expander)
    texts = [candidate.text for candidate in candidates]
    assert len(set(texts)) == len(texts) and all(candidate.source == StepSource.POLICY for candidate in candidates)


async def test_prefilled_generation_stops_before_the_closing_fence(policy_expander: PolicyExpander) -> None:
    candidates = await root_candidates(policy_expander)
    assert not any("```" in candidate.text for candidate in candidates)


async def test_statistics_count_every_sample(policy_expander: PolicyExpander) -> None:
    await expand_root(policy_expander)
    assert (policy_expander.statistics.requests, policy_expander.statistics.samples) == (1, SAMPLE_COUNT)


async def test_the_batch_charges_what_the_statistics_count(policy_expander: PolicyExpander) -> None:
    (batch,) = await expand_root(policy_expander)
    statistics = policy_expander.statistics
    assert (batch.prompt_tokens, batch.generated_tokens) == (statistics.prompt_tokens, statistics.generated_tokens)
