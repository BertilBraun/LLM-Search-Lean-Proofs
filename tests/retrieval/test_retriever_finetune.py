import random
from pathlib import Path

import pytest
import torch
import transformers

from lean_search.corpora.records import DataSplit, PremiseReference, TacticExample, TracedStep
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.finetune import (
    COMPETITION,
    LEANDOJO,
    RetrieverExample,
    RetrieverTrainingConfig,
    competition_examples,
    embed_in_chunks,
    leandojo_examples,
    planned_batches,
    reciprocal_ranks,
    train_retriever,
    training_batch,
    with_hard_negatives,
)
from lean_search.training.sft import DistributedContext

KNOWN = {"sq_nonneg", "mul_pos", "Real.sqrt_nonneg", "add_comm"}
PREMISE_TEXTS = {
    name: f"theorem <a>{name}</a> : True"
    for name in ("sq_nonneg", "mul_pos", "Real.sqrt_nonneg", "add_comm", "p1", "p2", "p3", "p4")
}


def traced(step: str, goal: str = "⊢ True", index: int = 0) -> TracedStep:
    return TracedStep("s", "proof", "t", DataSplit.TRAIN, "", "", index, 1, 1, (goal,), step, (), (), 0, 0.0)


def tactic(premises: tuple[str, ...]) -> TacticExample:
    references = tuple(PremiseReference(name, "Mathlib/X.lean") for name in premises)
    return TacticExample(
        "l", "thm#0", "train", "Mathlib/X.lean", "thm", 1, 0, "2 goals\n⊢ a", "rw", "rw", "", references
    )


def example(key: str, gold: tuple[str, ...], negatives: tuple[str, ...]) -> RetrieverExample:
    return RetrieverExample(key, COMPETITION, f"⊢ {key}", gold, negatives)


def tiny_model(directory: Path) -> str:
    config = transformers.T5Config(
        vocab_size=384, d_model=32, d_kv=8, d_ff=64, num_layers=2, num_heads=4, feed_forward_proj="gated-gelu"
    )
    torch.manual_seed(0)
    transformers.T5EncoderModel(config).save_pretrained(directory)
    return str(directory)


def test_competition_examples_keep_steps_that_name_a_known_premise() -> None:
    steps = [
        traced("nlinarith [sq_nonneg (a - b)]"),
        traced("linarith", index=1),
        traced("exact sqrt_nonneg x", index=2),
    ]
    assert [example.gold for example in competition_examples(steps, KNOWN)] == [("sq_nonneg",), ("Real.sqrt_nonneg",)]


def test_competition_examples_keep_each_goal_and_gold_once() -> None:
    steps = [traced("nlinarith [sq_nonneg a]"), traced("nlinarith [sq_nonneg a, h]", index=1)]
    assert len(competition_examples(steps, KNOWN)) == 1


@pytest.mark.parametrize(("premises", "gold"), [(("mul_pos", "unknown"), ("mul_pos",)), (("unknown",), None)])
def test_leandojo_examples_keep_known_gold_premises(premises: tuple[str, ...], gold: tuple[str, ...] | None) -> None:
    examples = leandojo_examples([tactic(premises)], KNOWN)
    assert (examples[0].gold if examples else None) == gold


def test_leandojo_queries_drop_the_goal_count() -> None:
    assert leandojo_examples([tactic(("mul_pos",))], KNOWN)[0].query == "⊢ a"


def test_leandojo_examples_are_marked_by_origin() -> None:
    assert leandojo_examples([tactic(("mul_pos",))], KNOWN)[0].origin == LEANDOJO


def test_hard_negatives_are_the_ranked_non_gold_premises() -> None:
    mined = with_hard_negatives(example("a", ("p2",), ()), ["p1", "p2", "p3"])
    assert mined.hard_negatives == ("p1", "p3")


def test_batch_labels_mark_every_gold_premise_of_each_query() -> None:
    examples = [example("a", ("p1", "p2"), ("p3",)), example("b", ("p3",), ("p4",))]
    batch = training_batch(examples, 1, random.Random(0))
    names = batch.premise_names
    assert [[names[column] for column, label in enumerate(row) if label] for row in batch.labels] == [
        [name for name in names if name in ("p1", "p2")],
        ["p3"],
    ]


def test_batch_premises_are_distinct() -> None:
    examples = [example("a", ("p1",), ("p2", "p3")), example("b", ("p1",), ("p2", "p3"))]
    batch = training_batch(examples, 2, random.Random(0))
    assert len(batch.premise_names) == len(set(batch.premise_names)) == 3


def test_planned_batches_cover_an_epoch_before_repeating() -> None:
    batches = planned_batches(10, 3, 3, seed=0)
    assert len({index for batch in batches for index in batch}) == 9


def test_reciprocal_rank_counts_premises_scored_above_the_best_gold() -> None:
    similarity = torch.tensor([[0.9, 0.5, 0.7], [0.1, 0.8, 0.2]])
    labels = torch.tensor([[0.0, 1.0, 0.0], [0.0, 1.0, 1.0]])
    assert reciprocal_ranks(similarity, labels).tolist() == pytest.approx([1 / 3, 1.0])


def test_chunked_embeddings_match_the_encoder(tmp_path: Path) -> None:
    encoder = TextEncoder(tiny_model(tmp_path), "cpu")
    texts = ["⊢ a + b = b + a", "x", "theorem <a>mul_pos</a> {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b"]
    with torch.no_grad():
        chunked = embed_in_chunks(encoder.model, texts, 1024, 64, torch.device("cpu"))
    assert torch.allclose(chunked, encoder.encode(texts), atol=1e-5)


def test_training_writes_a_loadable_encoder(tmp_path: Path) -> None:
    examples = [example(f"q{index}", (("p1", "p2", "p3", "p4")[index % 4],), ("p1", "p2", "p3")) for index in range(8)]
    config = RetrieverTrainingConfig(
        batch_examples=4,
        max_steps=3,
        max_training_seconds=0,
        evaluation_interval_steps=2,
        validation_examples=4,
        gradient_checkpointing=False,
    )
    output = tmp_path / "trained"
    train_retriever(
        tiny_model(tmp_path / "base"),
        examples,
        examples[:4],
        PREMISE_TEXTS,
        config,
        DistributedContext(0, 1, torch.device("cpu")),
        output,
        lambda record: None,
        lambda record: None,
    )
    assert TextEncoder(str(output), "cpu").encode(["⊢ True"]).shape == (1, 32)


def test_training_evaluates_at_start_interval_and_end(tmp_path: Path) -> None:
    examples = [example(f"q{index}", (("p1", "p2", "p3", "p4")[index % 4],), ("p1", "p2", "p3")) for index in range(8)]
    config = RetrieverTrainingConfig(
        batch_examples=4,
        max_steps=3,
        max_training_seconds=0,
        evaluation_interval_steps=2,
        validation_examples=4,
        gradient_checkpointing=False,
    )
    result = train_retriever(
        tiny_model(tmp_path / "base"),
        examples,
        examples[:4],
        PREMISE_TEXTS,
        config,
        DistributedContext(0, 1, torch.device("cpu")),
        tmp_path / "trained",
        lambda record: None,
        lambda record: None,
    )
    assert [evaluation.step for evaluation in result.evaluations] == [0, 2, 3]
