import dataclasses

import pytest
from rewritten_records import COUNTS, GOALS, TACTICS, example, proof

from lean_search.corpora.records import DataSplit
from lean_search.data_rewrite.chunks import ChunkLength
from lean_search.data_rewrite.dataset import (
    BuildConfig,
    ChunkExample,
    ChunkPosition,
    NameVariant,
    build_data,
    chunk_training_example,
    plan_chunks,
    proof_versions,
)
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExplanationOutcome,
    NamedStatus,
    ProofStatus,
    RewrittenProof,
)
from lean_search.data_rewrite.statistics import visible_block_tactics
from lean_search.policy.prompts import render_prompt, render_visible_completion
from lean_search.reasoning.dataset import ReasoningOrigin, tokenize_reasoning_example

CONFIG = BuildConfig(
    rewrite_run="run",
    variant=NameVariant.NUMBERED,
    chunk_lengths=(ChunkLength(1), ChunkLength(0)),
    non_visible_share=1.0,
    seed="test",
)
# One reasoning example: every chunk of one proof is planned for the visible mode.
VISIBLE_CONFIG = dataclasses.replace(CONFIG, visible_chunk_examples_per_reasoning_example=3.0, non_visible_share=0.0)
NAMED_EXPLANATION = "Since `hx_pos` makes $x$ positive, the shifted square is positive as well."
NUMBERED_EXPLANATION = "Since `h₀` makes $x$ positive, the shifted square is positive as well."


class CharacterTokenizer:
    """Qwen3.5's chat format with thinking off, one token per character."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + "<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def explanations_for(
    proofs: list[RewrittenProof], config: BuildConfig, outcome: ExplanationOutcome = ExplanationOutcome.EXPLAINED
) -> dict[ChunkPosition, ChunkExplanation]:
    explained = outcome is ExplanationOutcome.EXPLAINED
    return {
        planned.position: ChunkExplanation(
            *planned.position,
            outcome,
            NAMED_EXPLANATION if explained else "",
            NUMBERED_EXPLANATION if explained else "",
            (),
        )
        for planned in plan_chunks(proofs, [example()], config, COUNTS).visible
    }


def visible_chunk_examples(variant: NameVariant, outcome: ExplanationOutcome) -> list[ChunkExample]:
    config = dataclasses.replace(VISIBLE_CONFIG, variant=variant)
    data = build_data([proof("p/1")], [example()], config, COUNTS, explanations_for([proof("p/1")], config, outcome))
    return list(data.train_chunks)


@pytest.mark.parametrize(
    ("status", "named_status", "usable"),
    [
        (ProofStatus.KEPT, NamedStatus.RENAMED, True),
        (ProofStatus.KEPT, NamedStatus.NOTHING_TO_RENAME, True),
        (ProofStatus.KEPT, NamedStatus.REPLAY_FAILED, False),
        (ProofStatus.FLATTENING_CHANGED_BEHAVIOUR, NamedStatus.NOT_ATTEMPTED, False),
    ],
)
def test_a_proof_is_usable_only_in_both_variants(status: ProofStatus, named_status: NamedStatus, usable: bool) -> None:
    assert (proof_versions(proof("p/1", status=status, named_status=named_status)) is not None) == usable


def test_both_variants_hold_the_same_chunks() -> None:
    proofs = [proof(f"p/{index}") for index in range(5)]
    numbered = build_data(proofs, [], CONFIG, COUNTS)
    named = build_data(proofs, [], dataclasses.replace(CONFIG, variant=NameVariant.NAMED), COUNTS)
    assert [(chunk.proof_identifier, chunk.start, chunk.tactics) for chunk in numbered.train_chunks] == [
        (chunk.proof_identifier, chunk.start, chunk.tactics) for chunk in named.train_chunks
    ]


def test_named_chunks_carry_the_renamed_goals_and_tactics() -> None:
    data = build_data([proof("p/1")], [], dataclasses.replace(CONFIG, variant=NameVariant.NAMED), COUNTS)
    assert all("h₀" not in chunk.tactic_block + "".join(chunk.goals) for chunk in data.train_chunks)


def test_every_start_state_of_a_proof_is_a_prompt() -> None:
    data = build_data([proof("p/1")], [], CONFIG, COUNTS)
    assert sorted(chunk.start for chunk in data.train_chunks) == [0, 1, 2]


def test_chunk_end_state_follows_its_last_tactic() -> None:
    data = build_data([proof("p/1")], [], CONFIG, COUNTS)
    assert all(chunk.goals_after == GOALS[chunk.start + chunk.tactics] for chunk in data.train_chunks)


def test_chunks_over_the_completion_cap_are_shortened() -> None:
    config = dataclasses.replace(CONFIG, max_completion_tokens=len("nlinarith [hx_pos, h₁]"))
    data = build_data([proof("p/1")], [], config, COUNTS)
    assert {chunk.tactics for chunk in data.train_chunks} == {1}


def test_identical_chunks_of_two_proofs_are_kept_once() -> None:
    config = dataclasses.replace(CONFIG, chunk_lengths=(ChunkLength(1),))
    data = build_data([proof("p/1"), proof("p/2")], [], config, COUNTS)
    assert data.duplicate_chunks == len(data.train_chunks)


def distinct_one_tactic_proofs(count: int) -> list[RewrittenProof]:
    return [dataclasses.replace(proof(f"p/{index}"), goals=((f"x{index}",), *GOALS[1:])) for index in range(count)]


def test_non_visible_train_chunks_make_up_their_share_of_the_train_examples() -> None:
    config = dataclasses.replace(CONFIG, non_visible_share=2 / 3, chunk_lengths=(ChunkLength(1),))
    data = build_data(distinct_one_tactic_proofs(4), [example()], config, COUNTS)
    assert len(data.train_chunks) == 2


def test_visible_train_chunks_follow_their_ratio_to_the_reasoning_examples() -> None:
    config = dataclasses.replace(
        CONFIG, visible_chunk_examples_per_reasoning_example=2.0, non_visible_share=0.0, chunk_lengths=(ChunkLength(1),)
    )
    plan = plan_chunks(distinct_one_tactic_proofs(4), [example()], config, COUNTS)
    assert [planned.visible for planned in plan.train] == [True, True]


def test_non_visible_share_counts_the_visible_chunk_examples() -> None:
    config = dataclasses.replace(
        CONFIG, visible_chunk_examples_per_reasoning_example=1.0, non_visible_share=0.5, chunk_lengths=(ChunkLength(1),)
    )
    plan = plan_chunks(distinct_one_tactic_proofs(4), [example()], config, COUNTS)
    assert sum(not planned.visible for planned in plan.train) == 2


def test_explain_pass_and_both_arms_plan_the_same_visible_chunks() -> None:
    proofs = distinct_one_tactic_proofs(4)
    numbered = plan_chunks(proofs, [example()], VISIBLE_CONFIG, COUNTS)
    named = plan_chunks(proofs, [example()], dataclasses.replace(VISIBLE_CONFIG, variant=NameVariant.NAMED), COUNTS)
    assert [planned.position for planned in numbered.visible] == [planned.position for planned in named.visible]


def test_explained_chunks_become_visible_mode_examples() -> None:
    data = build_data(
        [proof("p/1")], [example()], VISIBLE_CONFIG, COUNTS, explanations_for([proof("p/1")], VISIBLE_CONFIG)
    )
    chunks = [entry for entry in data.train if entry.origin is ReasoningOrigin.RATIONALIZED]
    assert [(entry.visible, entry.reasoning) for entry in chunks] == [(True, NUMBERED_EXPLANATION)] * 3


@pytest.mark.parametrize(
    ("variant", "explanation"),
    [(NameVariant.NUMBERED, NUMBERED_EXPLANATION), (NameVariant.NAMED, NAMED_EXPLANATION)],
)
def test_each_arm_takes_its_variant_of_the_explanation(variant: NameVariant, explanation: str) -> None:
    chunks = visible_chunk_examples(variant, ExplanationOutcome.EXPLAINED)
    assert {chunk.explanation for chunk in chunks} == {explanation}


@pytest.mark.parametrize("outcome", [ExplanationOutcome.REJECTED, ExplanationOutcome.REQUEST_FAILED])
def test_chunk_without_an_accepted_explanation_stays_non_visible(outcome: ExplanationOutcome) -> None:
    chunks = visible_chunk_examples(NameVariant.NUMBERED, outcome)
    assert [chunk_training_example(chunk).reasoning for chunk in chunks] == [None] * 3


def test_planned_chunks_without_explanation_records_count_as_not_requested() -> None:
    data = build_data([proof("p/1")], [example()], VISIBLE_CONFIG, COUNTS, {})
    assert data.explanation_outcomes == {ExplanationOutcome.NOT_REQUESTED: 3}


def test_visible_chunk_example_is_prompted_in_the_visible_format() -> None:
    chunk = visible_chunk_examples(NameVariant.NAMED, ExplanationOutcome.EXPLAINED)[0]
    tokenizer = CharacterTokenizer()
    tokenized = tokenize_reasoning_example(tokenizer, chunk_training_example(chunk))
    prompt = "".join(map(chr, tokenized.input_ids[: tokenized.prompt_token_count]))
    assert prompt == render_prompt(tokenizer, chunk.goals, visible=True)


def test_visible_chunk_example_completes_with_explanation_then_block() -> None:
    chunk = visible_chunk_examples(NameVariant.NAMED, ExplanationOutcome.EXPLAINED)[0]
    tokenized = tokenize_reasoning_example(CharacterTokenizer(), chunk_training_example(chunk))
    completion = "".join(map(chr, tokenized.input_ids[tokenized.prompt_token_count :]))
    assert completion == render_visible_completion(NAMED_EXPLANATION, chunk.tactic_block)


def test_visible_block_lengths_add_the_explained_chunks_to_the_reasoning_examples() -> None:
    data = build_data(
        [proof("p/1")], [example()], VISIBLE_CONFIG, COUNTS, explanations_for([proof("p/1")], VISIBLE_CONFIG)
    )
    assert sum(row.after - row.before for row in visible_block_tactics(data)) == 3


def test_validation_lists_chunk_examples_before_reasoning_examples() -> None:
    data = build_data([proof("p/1", DataSplit.VALIDATION)], [example(DataSplit.VALIDATION)], CONFIG, COUNTS)
    assert [entry.reasoning is None for entry in data.validation] == [True, True, True, False]


def test_validation_lists_non_visible_chunks_then_visible_chunks_then_reasoning() -> None:
    config = dataclasses.replace(CONFIG, validation_chunk_examples=1, validation_visible_chunk_examples=2)
    proofs = [proof("p/1", DataSplit.VALIDATION)]
    examples = [example(DataSplit.VALIDATION)]
    explanations = {
        planned.position: ChunkExplanation(
            *planned.position, ExplanationOutcome.EXPLAINED, NAMED_EXPLANATION, NUMBERED_EXPLANATION, ()
        )
        for planned in plan_chunks(proofs, examples, config, COUNTS).visible
    }
    data = build_data(proofs, examples, config, COUNTS, explanations)
    assert [entry.origin for entry in data.validation] == [
        ReasoningOrigin.REPLAY,
        ReasoningOrigin.RATIONALIZED,
        ReasoningOrigin.RATIONALIZED,
        ReasoningOrigin.SAMPLED,
    ]


def test_numbered_reasoning_example_keeps_its_explanation_with_the_flat_block() -> None:
    data = build_data([], [example()], CONFIG, COUNTS)
    assert (data.train[0].tactic_block, data.train[0].reasoning) == (
        "have h₁ : 0 < x + 1\nlinarith [h₀]\nnlinarith [h₀, h₁]",
        "Since h₀ gives 0 < x, the square plus one is positive.",
    )


def test_named_reasoning_example_renames_its_explanation() -> None:
    data = build_data([], [example()], dataclasses.replace(CONFIG, variant=NameVariant.NAMED), COUNTS)
    assert data.train[0].reasoning == "Since hx_pos gives 0 < x, the square plus one is positive."


def test_reasoning_example_unusable_when_named_is_dropped_from_both_variants() -> None:
    data = build_data([], [example(named_status=NamedStatus.STATES_DIFFER)], CONFIG, COUNTS)
    assert data.train == ()


def test_chunks_containing_a_tactic_with_a_nested_proof_are_dropped() -> None:
    nested = "have h₁ : 0 < x + 1 := by\n  intro y\n  all_goals linarith [h₀]"
    record = dataclasses.replace(proof("p/1"), tactics=(nested, *TACTICS[2:]), goals=(GOALS[0], GOALS[2], GOALS[3]))
    record = dataclasses.replace(record, named=dataclasses.replace(record.named, status=NamedStatus.NOTHING_TO_RENAME))
    data = build_data([record], [], CONFIG, COUNTS)
    assert [chunk.start for chunk in data.train_chunks] == [1]


def test_both_variants_list_their_examples_in_the_same_order() -> None:
    examples = [
        dataclasses.replace(example(), original=dataclasses.replace(example().original, step_index=index))
        for index in range(6)
    ]
    numbered = build_data([proof("p/1")], examples, CONFIG, COUNTS)
    named = build_data([proof("p/1")], examples, dataclasses.replace(CONFIG, variant=NameVariant.NAMED), COUNTS)
    assert [(entry.proof_identifier, entry.step_index) for entry in numbered.train] == [
        (entry.proof_identifier, entry.step_index) for entry in named.train
    ]
