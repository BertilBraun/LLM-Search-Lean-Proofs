import dataclasses

import pytest

from lean_search.corpora.records import DataSplit
from lean_search.data_rewrite.chunks import ChunkLength
from lean_search.data_rewrite.dataset import (
    BuildConfig,
    NameVariant,
    TokenCounts,
    build_data,
    proof_versions,
)
from lean_search.data_rewrite.naming import NameChange, NameSource, renamed_text
from lean_search.data_rewrite.records import (
    ExampleStatus,
    NamedExample,
    NamedProof,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin

CHANGES = (NameChange("h₀", "hx_pos", NameSource.RULES),)
TACTICS = ("have h₁ : 0 < x + 1", "linarith [h₀]", "nlinarith [h₀, h₁]")
GOALS = (
    ("x : ℝ\nh₀ : 0 < x\n⊢ 0 < x ^ 2 + 1",),
    ("case h₁\nx : ℝ\nh₀ : 0 < x\n⊢ 0 < x + 1", "x : ℝ\nh₀ : 0 < x\nh₁ : 0 < x + 1\n⊢ 0 < x ^ 2 + 1"),
    ("x : ℝ\nh₀ : 0 < x\nh₁ : 0 < x + 1\n⊢ 0 < x ^ 2 + 1",),
    (),
)
CONFIG = BuildConfig(
    rewrite_run="run",
    variant=NameVariant.NUMBERED,
    chunk_lengths=(ChunkLength(1), ChunkLength(0)),
    chunk_examples_per_reasoning_example=0.0,
    seed="test",
)
COUNTS = TokenCounts(prompt=lambda goals: sum(len(goal) for goal in goals), completion=len)


def renamed_goals(goals: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(renamed_text(goal, CHANGES) for goal in state) for state in goals)


def proof(
    identifier: str,
    split: DataSplit = DataSplit.TRAIN,
    status: ProofStatus = ProofStatus.KEPT,
    named_status: NamedStatus = NamedStatus.RENAMED,
) -> RewrittenProof:
    named = NamedProof(
        named_status,
        CHANGES,
        (),
        "",
        tuple(renamed_text(tactic, CHANGES) for tactic in TACTICS),
        renamed_goals(GOALS),
    )
    return RewrittenProof(
        source="test",
        proof_identifier=identifier,
        split=split,
        header="",
        formal_statement=f"theorem {identifier.replace('/', '_')} (x : ℝ) (h₀ : 0 < x) : 0 < x ^ 2 + 1 := by",
        original_tactics=2,
        flattened=True,
        status=status,
        message="",
        tactics=TACTICS,
        goals=GOALS,
        named=named,
        lean_seconds=1.0,
    )


def example(split: DataSplit = DataSplit.TRAIN, named_status: NamedStatus = NamedStatus.RENAMED) -> RewrittenExample:
    original = ReasoningExample(
        "test",
        "test/reasoning",
        0,
        GOALS[0],
        "have h₁ : 0 < x + 1 := by\n  linarith [h₀]\nnlinarith [h₀, h₁]",
        "Since h₀ gives 0 < x, the square plus one is positive.",
        "",
        ReasoningOrigin.SAMPLED,
        visible=True,
    )
    named = NamedExample(
        named_status,
        CHANGES,
        (),
        renamed_goals(GOALS)[0],
        renamed_text("have h₁ : 0 < x + 1\nlinarith [h₀]\nnlinarith [h₀, h₁]", CHANGES),
        renamed_text(original.reasoning or "", CHANGES),
        (),
    )
    return RewrittenExample(
        original,
        split,
        ExampleStatus.KEPT,
        "",
        True,
        "have h₁ : 0 < x + 1\nlinarith [h₀]\nnlinarith [h₀, h₁]",
        (),
        named,
        1.0,
    )


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


def test_train_chunks_follow_the_reasoning_ratio() -> None:
    config = dataclasses.replace(CONFIG, chunk_examples_per_reasoning_example=2.0, chunk_lengths=(ChunkLength(1),))
    proofs = [dataclasses.replace(proof(f"p/{index}"), goals=((f"x{index}",), *GOALS[1:])) for index in range(4)]
    data = build_data(proofs, [example()], config, COUNTS)
    assert len(data.train_chunks) == 2


def test_validation_lists_chunk_examples_before_reasoning_examples() -> None:
    data = build_data([proof("p/1", DataSplit.VALIDATION)], [example(DataSplit.VALIDATION)], CONFIG, COUNTS)
    assert [entry.reasoning is None for entry in data.validation] == [True, True, True, False]


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
