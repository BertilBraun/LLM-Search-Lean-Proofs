import asyncio

import huggingface_hub
import pytest
import torch
import transformers

from lean_search.retrieval.config import DEFAULT_RETRIEVER
from lean_search.retrieval.encoder import TextEncoder, byte_token_ids, length_batches
from lean_search.retrieval.index import PremiseIndex
from lean_search.retrieval.premises import RetrievedPremise
from lean_search.retrieval.retriever import BatchingRetriever, GoalRetriever

TEXTS = ["a b : ℕ\n⊢ a + b = b + a", "<a>Nat.add_comm</a> (n m : ℕ) : n + m = m + n", "x" * 2000]
retriever_is_cached = isinstance(huggingface_hub.try_to_load_from_cache(DEFAULT_RETRIEVER, "config.json"), str)
needs_retriever = pytest.mark.skipif(not retriever_is_cached, reason=f"{DEFAULT_RETRIEVER} is not downloaded")


@pytest.mark.parametrize("text", TEXTS)
def test_byte_tokens_match_the_byt5_tokenizer(text: str) -> None:
    tokenizer = transformers.ByT5Tokenizer()
    assert byte_token_ids(text, 1024) == tokenizer(text, truncation=True, max_length=1024)["input_ids"]


def test_length_batches_stay_within_the_padded_budget() -> None:
    assert length_batches([3, 10, 4, 9, 2], max_batch_tokens=20) == [[1, 3], [2, 0, 4]]


def test_index_returns_the_best_scores_first() -> None:
    embeddings = torch.tensor([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])
    index = PremiseIndex(["x", "y", "diagonal"], ["x : True", "y : True", "diagonal : True"], embeddings)
    assert index.search(torch.tensor([[0.0, 1.0]]), 2) == [
        (RetrievedPremise("y", "y : True", 1.0), RetrievedPremise("diagonal", "diagonal : True", pytest.approx(0.8)))
    ]


@pytest.fixture(scope="module")
def encoder() -> TextEncoder:
    return TextEncoder(DEFAULT_RETRIEVER, "cpu")


@needs_retriever
def test_embeddings_do_not_depend_on_the_batch(encoder: TextEncoder) -> None:
    together = encoder.encode(TEXTS[:2])
    alone = torch.cat([encoder.encode([text]) for text in TEXTS[:2]])
    assert torch.allclose(together, alone, atol=1e-5)


@needs_retriever
def test_embeddings_have_unit_norm(encoder: TextEncoder) -> None:
    assert torch.allclose(encoder.encode(TEXTS).norm(dim=1), torch.ones(len(TEXTS)))


@needs_retriever
def test_retriever_ranks_the_matching_premise_first(encoder: TextEncoder) -> None:
    names = ["Nat.add_comm", "Real.sqrt_nonneg", "Finset.sum_range_succ"]
    codes = [
        "theorem <a>Nat.add_comm</a> : ∀ (n m : ℕ), n + m = m + n",
        "theorem <a>Real.sqrt_nonneg</a> (x : ℝ) : 0 ≤ √x",
        "theorem <a>Finset.sum_range_succ</a> (f : ℕ → M) (n : ℕ) : ∑ x ∈ range (n + 1), f x = ∑ x ∈ range n, f x",
    ]
    index = PremiseIndex(names, names, encoder.encode(codes))
    (retrieved,) = GoalRetriever(encoder, index).retrieve([["x : ℝ\n⊢ 0 ≤ √x"]], 3)
    assert retrieved[0].full_name == "Real.sqrt_nonneg"


@needs_retriever
async def test_concurrent_requests_share_batches(encoder: TextEncoder) -> None:
    names = ["Nat.add_comm", "Real.sqrt_nonneg"]
    index = PremiseIndex(names, names, encoder.encode(names))
    batching = BatchingRetriever(GoalRetriever(encoder, index), count=1, max_batch_goals=8)
    await asyncio.gather(*(batching.retrieve([f"⊢ {number} = {number}"]) for number in range(5)))
    assert (batching.statistics.goals, batching.statistics.batches) == (5, 1)
