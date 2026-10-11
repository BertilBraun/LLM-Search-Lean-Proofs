from collections.abc import Callable
from pathlib import Path

import pytest

from lean_search.corpora.records import DataSplit, TracedStep, write_jsonl
from lean_search.training.sft_data import (
    IGNORE_INDEX,
    SftExample,
    SourceStream,
    TokenizedExample,
    deduplicate,
    duplicate_key,
    length_capped_tokenizer,
    read_examples,
    read_traced_examples,
    select_mixture,
    select_validation,
    sft_example,
    shard_step_files,
    snapshot_step_files,
    tokenize_example,
    write_examples,
)

GOALS = ("x : ℕ\nh : x + 1 = 3\n⊢ x = 2",)
SEED = "test"


class CharacterTokenizer:
    """ChatML turns with an empty think block when thinking is off, one token per character."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + (
            "<|im_start|>assistant\n" if enable_thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def decode(token_ids: tuple[int, ...]) -> str:
    return "".join(chr(token_id) for token_id in token_ids)


def example(source: str, number: int, goals: tuple[str, ...] = GOALS, step: str = "omega") -> SftExample:
    return SftExample(source, f"{source}/0/{number}", 0, goals, step)


def fixed_length(token_count: int) -> Callable[[SftExample], TokenizedExample]:
    def tokenize(example: SftExample) -> TokenizedExample:
        return TokenizedExample(example, (1,) * token_count, token_count - 2)

    return tokenize


def distinct_examples(source: str, count: int) -> list[SftExample]:
    return [example(source, number, goals=(f"⊢ {number} = {number}",)) for number in range(count)]


def selected_tokens(sizes: dict[str, int], weights: dict[str, float], budget: int) -> dict[str, int]:
    streams = {
        source: SourceStream(distinct_examples(source, size), fixed_length(10)) for source, size in sizes.items()
    }
    select_mixture(streams, weights, budget)
    return {source: stream.tokens for source, stream in streams.items()}


TOKENIZED = tokenize_example(CharacterTokenizer(), example("source", 1, step="subst h\nrfl"))


def test_prompt_ends_with_the_empty_think_block_and_the_prefilled_fence() -> None:
    assert decode(TOKENIZED.input_ids[: TOKENIZED.prompt_token_count]).endswith(
        "<|im_start|>assistant\n<think>\n\n</think>\n\n```lean\n"
    )


def test_prompt_shows_the_goals_in_the_user_turn() -> None:
    assert f"```lean\n{GOALS[0]}\n```<|im_end|>" in decode(TOKENIZED.input_ids[: TOKENIZED.prompt_token_count])


def test_completion_is_the_step_the_closing_fence_and_the_end_of_turn() -> None:
    assert decode(TOKENIZED.input_ids[TOKENIZED.prompt_token_count :]) == "subst h\nrfl\n```<|im_end|>"


def test_labels_ignore_every_prompt_token() -> None:
    assert set(TOKENIZED.labels[: TOKENIZED.prompt_token_count]) == {IGNORE_INDEX}


def test_labels_are_the_completion_tokens_after_the_prompt() -> None:
    assert TOKENIZED.labels[TOKENIZED.prompt_token_count :] == TOKENIZED.input_ids[TOKENIZED.prompt_token_count :]


def test_steps_are_normalized_like_generated_blocks() -> None:
    assert sft_example("source", "source/0/1", 0, GOALS, "nlinarith [sq_nonneg x]   \n").tactic_block == (
        "nlinarith [sq_nonneg x]"
    )


def test_identical_goals_and_step_are_kept_once_across_sources() -> None:
    pool = deduplicate({"first": [example("first", 1)], "second": [example("second", 2)]}, SEED)
    assert [len(examples) for examples in pool.examples_by_source.values()] == [1, 0]


def test_the_same_goals_with_different_steps_are_both_kept() -> None:
    pool = deduplicate({"first": [example("first", 1, step="omega"), example("first", 2, step="linarith")]}, SEED)
    assert len(pool.examples_by_source["first"]) == 2


def test_duplicates_are_counted_for_the_source_that_lost_them() -> None:
    pool = deduplicate({"first": [example("first", 1)], "second": [example("second", 2)]}, SEED)
    assert pool.duplicates_by_source["second"] == 1


def test_excluded_keys_drop_validation_pairs_seen_in_train() -> None:
    pool = deduplicate({"first": [example("first", 1)]}, SEED, excluded_keys={duplicate_key(example("other", 9))})
    assert pool.examples_by_source["first"] == []


def test_deduplication_order_does_not_depend_on_the_input_order() -> None:
    examples = distinct_examples("first", 20)
    forward = deduplicate({"first": examples}, SEED).examples_by_source["first"]
    assert deduplicate({"first": examples[::-1]}, SEED).examples_by_source["first"] == forward


def test_different_seeds_give_different_orders() -> None:
    examples = distinct_examples("first", 20)
    assert (
        deduplicate({"first": examples}, "a").examples_by_source["first"]
        != deduplicate({"first": examples}, "b").examples_by_source["first"]
    )


def test_mixture_shares_follow_the_weights() -> None:
    assert selected_tokens({"first": 100, "second": 100}, {"first": 3.0, "second": 1.0}, 400) == {
        "first": 300,
        "second": 100,
    }


def test_the_share_of_an_exhausted_source_goes_to_the_others() -> None:
    assert selected_tokens({"small": 5, "large": 100}, {"small": 1.0, "large": 1.0}, 400) == {
        "small": 50,
        "large": 350,
    }


def test_a_zero_weight_source_is_not_selected() -> None:
    assert selected_tokens({"first": 10, "second": 10}, {"first": 1.0, "second": 0.0}, 50)["second"] == 0


def test_a_zero_budget_takes_every_example() -> None:
    assert selected_tokens({"first": 7, "second": 3}, {"first": 1.0, "second": 5.0}, 0) == {"first": 70, "second": 30}


def test_over_length_examples_are_skipped_and_counted() -> None:
    long_goal = example("first", 1, goals=("⊢ " + "x" * 500,))
    stream = SourceStream([long_goal, example("first", 2)], length_capped_tokenizer(CharacterTokenizer(), 400, 50))
    stream.extend_to(1)
    assert (stream.over_length, len(stream.accepted)) == (1, 1)


@pytest.mark.parametrize(("prompt_cap", "completion_cap"), [(10, 100), (1000, 5)])
def test_either_length_cap_rejects_an_example(prompt_cap: int, completion_cap: int) -> None:
    assert length_capped_tokenizer(CharacterTokenizer(), prompt_cap, completion_cap)(example("first", 1)) is None


def test_validation_takes_the_requested_number_of_examples() -> None:
    selected = select_validation({"first": distinct_examples("first", 30)}, 12, SEED, fixed_length(10))
    assert len(selected) == 12


def traced_step(split: DataSplit, step: str, number: int = 1) -> TracedStep:
    return TracedStep(
        source="first",
        proof_identifier=f"first/0/{number}",
        statement_identifier=f"statement_{number}",
        split=split,
        header="import Mathlib",
        formal_statement="theorem t (x : ℕ) (h : x + 1 = 3) : x = 2 := by",
        step_index=0,
        total_steps=1,
        remaining_steps=1,
        goals_before=GOALS,
        step=step,
        goals_after=(),
        previous_steps=(),
        heartbeats=100,
        elapsed_seconds=0.01,
    )


def traced_directory(tmp_path: Path, steps: list[TracedStep]) -> Path:
    write_jsonl(tmp_path / "shards" / "first" / "pilot_0000.steps.jsonl", steps)
    return tmp_path


def test_forbidden_steps_are_dropped_and_counted(tmp_path: Path) -> None:
    directory = traced_directory(
        tmp_path, [traced_step(DataSplit.TRAIN, "native_decide"), traced_step(DataSplit.TRAIN, "omega", 2)]
    )
    traced = read_traced_examples(shard_step_files(directory), ["first"])
    assert ([example.tactic_block for example in traced.train["first"]], traced.forbidden["first"]) == (["omega"], 1)


def test_validation_split_steps_are_read_separately(tmp_path: Path) -> None:
    directory = traced_directory(tmp_path, [traced_step(DataSplit.VALIDATION, "omega")])
    traced = read_traced_examples(shard_step_files(directory), ["first"])
    assert (len(traced.train["first"]), len(traced.validation["first"])) == (0, 1)


def test_unselected_sources_are_ignored(tmp_path: Path) -> None:
    directory = traced_directory(tmp_path, [traced_step(DataSplit.TRAIN, "omega")])
    assert read_traced_examples(shard_step_files(directory), ["second"]).train == {"second": []}


def test_examples_round_trip_through_json_lines(tmp_path: Path) -> None:
    examples = [example("first", 1, goals=("a : ℕ\n⊢ a = a", "⊢ True")), example("first", 2, step="rfl")]
    write_examples(tmp_path / "train.jsonl", examples)
    assert list(read_examples(tmp_path / "train.jsonl")) == examples


def test_qwen_completion_ends_with_the_end_of_turn_token() -> None:
    transformers = pytest.importorskip("transformers")
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained("Qwen/Qwen3.5-0.8B", local_files_only=True)
    except OSError:
        pytest.skip("Qwen/Qwen3.5-0.8B is not in the Hugging Face cache")
    tokenized = tokenize_example(tokenizer, example("first", 1))
    assert tokenized.input_ids[-1] == tokenizer.convert_tokens_to_ids("<|im_end|>")


def test_the_snapshot_is_the_merged_train_and_validation_files(tmp_path: Path) -> None:
    assert [path.name for path in snapshot_step_files(tmp_path)] == ["steps_train.jsonl", "steps_validation.jsonl"]
