import dataclasses
from collections.abc import Sequence

import pytest
from graph_trees import GraphBuilder

from lean_search.policy.config import StepLogProbability
from lean_search.rl.step1_settings import progressing_step_values
from lean_search.search import FailureKind, StepSource, TreeRecord
from lean_search.search.texts import ExpansionTexts, SampledCompletion, SampledTokens

ROOT = "x : ℕ\n⊢ x + 0 = x"
AFTER_FIRST = "x : ℕ\n⊢ x = x"


class CharacterDecoder:
    """One token per character."""

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(map(chr, token_ids))


def completion(edge_id: int, block: str, block_log_probability: float) -> SampledCompletion:
    """A visible sample: an explanation, then the block in a fence; each block character one token."""
    text = f"Simplify.\n```lean\n{block}\n```"
    start = text.index(block)
    log_probabilities = tuple(
        block_log_probability if start <= index < start + len(block) else -0.1 for index in range(len(text))
    )
    return SampledCompletion(edge_id, text, (), True, SampledTokens(tuple(map(ord, text)), log_probabilities))


def calibration_tree() -> TreeRecord:
    """Two expansions: at the root a block that changed the goals (two merged samples), one that left them as they
    were, a failing one and an automation step; below it a block that closed them."""
    builder = GraphBuilder(ROOT)
    root = builder.root
    first = builder.child(root, AFTER_FIRST, text="simp only [Nat.add_zero]", sample_count=2)
    builder.duplicate(root, root, text="skip")
    builder.failure(root, FailureKind.ERROR, text="linarith")
    builder.child(root, text="omega", source=StepSource.AUTOMATION)
    proved = builder.child(first, text="rfl")
    record = builder.record(proved)
    first_edge, proving_edge = first.edge_id, proved.edge_id
    assert first_edge is not None and proving_edge is not None
    root_samples = (
        completion(first_edge, "simp only [Nat.add_zero]", -0.5),
        completion(first_edge, "simp only [Nat.add_zero]", -1.0),
    )
    expansions = (
        ExpansionTexts("t", 0, "prompt", root_samples),
        ExpansionTexts("t", first.node_id, "prompt", (completion(proving_edge, "rfl", -0.2),)),
    )
    return dataclasses.replace(record, expansions=expansions)


def values(setting: StepLogProbability) -> list[float]:
    return progressing_step_values(calibration_tree(), setting, CharacterDecoder(), visible=True)


def test_completion_takes_the_value_each_progressing_edge_recorded_at_every_depth() -> None:
    assert values(StepLogProbability.COMPLETION) == [-1.0, -1.0]


def test_block_sum_is_the_best_merged_samples_sum_over_the_blocks_tokens() -> None:
    assert values(StepLogProbability.BLOCK_SUM) == pytest.approx([-0.5 * 24, -0.2 * 3])


def test_block_mean_is_the_best_merged_samples_mean_over_the_blocks_tokens() -> None:
    assert values(StepLogProbability.BLOCK_MEAN) == pytest.approx([-0.5, -0.2])
