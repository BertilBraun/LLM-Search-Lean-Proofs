import pytest

from lean_search.retrieval.premises import RetrievedPremise
from lean_search.retrieval.sft_data import (
    LemmaSftExample,
    ProofUnit,
    inject_step_premises,
    lemma_count_for,
    select_proofs,
    subsample_indices,
    tokenize_lemma_example,
)

CANDIDATES = tuple(RetrievedPremise(f"p{rank}", f"p{rank} : True", 1.0 - rank / 10) for rank in range(8))
NAMED = (RetrievedPremise("gold", "gold : True", 0.0),)


class CharacterTokenizer:
    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        return "".join(f"<{turn['role']}>{turn['content']}" for turn in conversation) + "<assistant>"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def unit(source: str, name: str, tokens: int) -> ProofUnit:
    return ProofUnit(source, name, (), tokens)


def test_lemma_counts_cover_every_arm() -> None:
    counts = {lemma_count_for(f"step{index}", (0, 4, 8, 16, 32), "seed") for index in range(200)}
    assert counts == {0, 4, 8, 16, 32}


def test_injection_keeps_the_candidate_count() -> None:
    assert len(inject_step_premises(CANDIDATES, NAMED, "step", "seed")) == len(CANDIDATES)


def test_injection_drops_the_lowest_ranked_candidate() -> None:
    names = {premise.full_name for premise in inject_step_premises(CANDIDATES, NAMED, "step", "seed")}
    assert names == {*(f"p{rank}" for rank in range(7)), "gold"}


def test_injected_premise_takes_the_score_of_its_rank() -> None:
    injected = inject_step_premises(CANDIDATES, NAMED, "step", "seed")
    position = next(index for index, premise in enumerate(injected) if premise.full_name == "gold")
    assert injected[position].score == CANDIDATES[position].score


@pytest.mark.parametrize(
    ("budget", "selected"),
    [
        (40, {"a": ["a1", "a2"], "b": ["b1", "b2"]}),
        (100, {"a": ["a1", "a2", "a3", "a4"], "b": ["b1", "b2"]}),
        (0, {"a": ["a1", "a2", "a3", "a4"], "b": ["b1", "b2"]}),
    ],
)
def test_proof_selection_gives_exhausted_shares_to_other_sources(budget: int, selected: dict[str, list[str]]) -> None:
    proofs = {
        "a": [unit("a", f"a{index}", 10) for index in range(1, 5)],
        "b": [unit("b", "b1", 10), unit("b", "b2", 10)],
    }
    chosen = select_proofs(proofs, budget)
    assert {source: [proof.proof_identifier for proof in units] for source, units in chosen.items()} == selected


def test_lemma_example_prompt_carries_the_lemmas() -> None:
    example = LemmaSftExample("s", "p", 0, ("⊢ True",), ("trivial : True  -- exact: closes the goal",), "trivial", 4)
    tokenized = tokenize_lemma_example(CharacterTokenizer(), example)
    prompt = "".join(chr(token) for token in tokenized.input_ids[: tokenized.prompt_token_count])
    assert "Lemmas that may help:\n```lean\ntrivial : True  -- exact: closes the goal\n```" in prompt


def example(index: int, lemma_count: int) -> LemmaSftExample:
    return LemmaSftExample("s", f"p{index}", 0, ("⊢ True",), (), "trivial", lemma_count)


def subsampled_tokens_by_length() -> dict[int, int]:
    examples = [example(index, (0, 8, 32)[index % 3]) for index in range(3000)]
    counts = [(100, 300, 900)[index % 3] for index in range(3000)]
    tokens = {0: 0, 8: 0, 32: 0}
    for index in subsample_indices(examples, counts, 260_000, "seed"):
        tokens[examples[index].lemma_count] += counts[index]
    return tokens


def test_subsample_meets_the_token_budget() -> None:
    assert sum(subsampled_tokens_by_length().values()) == pytest.approx(260_000, rel=0.01)


def test_subsample_keeps_each_list_lengths_token_share() -> None:
    tokens = subsampled_tokens_by_length()
    assert (tokens[0] / 20_000, tokens[8] / 60_000, tokens[32] / 180_000) == pytest.approx((1, 1, 1), rel=0.01)


def test_subsample_indices_ascend() -> None:
    indices = subsample_indices([example(index, 4) for index in range(100)], [10] * 100, 500, "seed")
    assert indices == sorted(indices)
