"""Rejection-sampled reasoning SFT data: successful samples per state, rendered with thinking on, plus replay."""

import dataclasses
import json
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.tracing import stable_fraction
from lean_search.policy.prompts import render_prompt, render_thinking_completion, render_visible_completion
from lean_search.reasoning.records import SampleRecord, StateRecord, StateSamples, scored_samples
from lean_search.reasoning.reward import RewardConfig
from lean_search.reasoning.thinking import is_trainable_reasoning
from lean_search.training.math_data import MathSolution
from lean_search.training.sft_data import SftExample, TokenizedExample, Tokenizer, ordering_key, tokenize_example


@dataclass(frozen=True)
class SelectionConfig:
    max_per_state: int = 2
    # Shorter successes are kept first, but an empty or near-empty thought teaches nothing about reasoning.
    min_reasoning_tokens: int = 16
    # 0 keeps every length the sampling cap allowed.
    max_reasoning_tokens: int = 0


@dataclass(frozen=True)
class ReasoningDataConfig:
    # Reasoning runs (names under $LEAN_SEARCH_RUNS) whose records feed the data.
    runs: tuple[str, ...]
    reward: RewardConfig = field(default_factory=RewardConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    # Non-thinking SFT data (name under $LEAN_SEARCH_DATA/sft) replayed so the non-thinking mode is kept.
    replay_data: str = "v2"
    # Replay examples per reasoning example in train.
    replay_ratio: float = 1.0
    # Fraction of the proofs whose selected samples are held out for validation.
    validation_fraction: float = 0.03
    validation_replay_examples: int = 500
    # Above 0, successful reasoning longer than this enters only through a sufficient compression (and states
    # without a thinking success through rationalized steps), from the runs' `shorten` records of this name.
    max_kept_reasoning_tokens: int = 0
    shortening: str = ""
    tokenizer: str = "Qwen/Qwen3.5-2B"
    seed: str = "reasoning-data"
    # Set, it replaces the sampling runs' system prompt addition in the reasoning examples, so that a teacher's
    # brevity instruction does not become part of the student's prompt.
    thinking_instruction: str | None = None
    # General math worked solutions (name under $LEAN_SEARCH_DATA/math_sft) replayed alongside, this many per
    # reasoning example in train (written to math.jsonl next to train.jsonl).
    math_replay_data: str = ""
    math_replay_ratio: float = 0.0
    # Train reasoning examples with fewer reasoning tokens than this make up at most max_short_share of them; the
    # earlier runs' are kept first (list a teacher before the policy's own samples).
    short_reasoning_tokens: int = 0
    max_short_share: float = 1.0
    # Reasoning examples of another data set (name under $LEAN_SEARCH_DATA/reasoning, e.g. thinking-format traces so
    # that a think block keeps working), this many per train reasoning example.
    extra_reasoning_data: str = ""
    extra_reasoning_ratio: float = 0.0


class ReasoningOrigin(StrEnum):
    SAMPLED = "sampled"
    COMPRESSED = "compressed"
    RATIONALIZED = "rationalized"
    # A non-thinking SFT example.
    REPLAY = "replay"


@dataclass(frozen=True)
class ReasoningExample:
    source: str
    proof_identifier: str
    step_index: int
    goals: tuple[str, ...]
    tactic_block: str
    # None for a non-thinking replay example.
    reasoning: str | None
    # The thinking-mode system prompt addition the reasoning was sampled with.
    thinking_instruction: str
    origin: ReasoningOrigin
    # The reasoning is written visibly before the block, with thinking off (PolicyConfig.visible_reasoning).
    visible: bool = False


def trainable_successes(record: StateRecord, reward: RewardConfig, selection: SelectionConfig) -> list[SampleRecord]:
    return [
        scored.sample
        for scored in scored_samples(record, reward)
        if scored.success
        and not scored.sample.forced
        and is_trainable_reasoning(scored.sample.reasoning)
        and scored.sample.reasoning_tokens >= selection.min_reasoning_tokens
        and (not selection.max_reasoning_tokens or scored.sample.reasoning_tokens <= selection.max_reasoning_tokens)
    ]


def ordered_successes(record: StateRecord, reward: RewardConfig, selection: SelectionConfig) -> list[SampleRecord]:
    """Trainable successes, shortest reasoning first, distinct blocks before repeated ones."""
    successes = sorted(
        trainable_successes(record, reward, selection), key=lambda sample: (sample.reasoning_tokens, sample.index)
    )
    seen_blocks: set[str] = set()
    distinct: list[SampleRecord] = []
    repeated: list[SampleRecord] = []
    for sample in successes:
        assert sample.tactic_block is not None
        (repeated if sample.tactic_block in seen_blocks else distinct).append(sample)
        seen_blocks.add(sample.tactic_block)
    return distinct + repeated


def select_samples(record: StateRecord, reward: RewardConfig, selection: SelectionConfig) -> list[SampleRecord]:
    return ordered_successes(record, reward, selection)[: selection.max_per_state]


def reasoning_example(sampled: StateSamples, sample: SampleRecord) -> ReasoningExample:
    assert sample.tactic_block is not None
    step = sampled.state.step
    return ReasoningExample(
        step.source,
        step.proof_identifier,
        step.step_index,
        sampled.state.goals,
        sample.tactic_block,
        sample.reasoning,
        sampled.thinking_instruction,
        ReasoningOrigin.SAMPLED,
        sampled.visible,
    )


def with_thinking_instruction(examples: Iterable[ReasoningExample], instruction: str | None) -> list[ReasoningExample]:
    if instruction is None:
        return list(examples)
    return [dataclasses.replace(example, thinking_instruction=instruction) for example in examples]


def replay_example(example: SftExample) -> ReasoningExample:
    return ReasoningExample(
        example.source,
        example.proof_identifier,
        example.step_index,
        example.goals,
        example.tactic_block,
        None,
        "",
        ReasoningOrigin.REPLAY,
    )


def is_validation_proof(proof_identifier: str, fraction: float, seed: str) -> bool:
    return stable_fraction(proof_identifier, f"{seed} validation") < fraction


@dataclass(frozen=True)
class RankedExample:
    # Position of the example's run in ReasoningDataConfig.runs.
    run_index: int
    reasoning_tokens: int
    example: ReasoningExample


def example_key(example: ReasoningExample) -> str:
    return f"{example.proof_identifier}#{example.step_index}#{example.reasoning}"


def capped_short_examples(
    ranked: Sequence[RankedExample], short_tokens: int, max_share: float, seed: str
) -> list[ReasoningExample]:
    """All long examples and at most max_share of the result short ones, earlier runs first."""
    if not short_tokens or max_share >= 1:
        return [entry.example for entry in ranked]
    long = [entry.example for entry in ranked if entry.reasoning_tokens >= short_tokens]
    short = sorted(
        (entry for entry in ranked if entry.reasoning_tokens < short_tokens),
        key=lambda entry: (entry.run_index, stable_fraction(example_key(entry.example), f"{seed} short")),
    )
    kept = math.floor(max_share * len(long) / (1 - max_share))
    return long + [entry.example for entry in short[:kept]]


def extra_reasoning(examples: Iterable[ReasoningExample], count: int, seed: str) -> list[ReasoningExample]:
    reasoning = [example for example in examples if example.reasoning is not None]
    return sorted(reasoning, key=lambda example: stable_fraction(example_key(example), f"{seed} extra"))[:count]


def math_replay(solutions: Iterable[MathSolution], count: int, seed: str) -> list[MathSolution]:
    ordered = sorted(solutions, key=lambda solution: stable_fraction(solution.identifier, f"{seed} math"))
    return ordered[:count]


def replay_examples(examples: Iterable[SftExample], count: int, seed: str) -> list[ReasoningExample]:
    ordered = sorted(examples, key=lambda example: ordering_key(example, seed))
    return [replay_example(example) for example in ordered[:count]]


def tokenize_reasoning_example(tokenizer: Tokenizer, example: ReasoningExample) -> TokenizedExample:
    """Thinking examples: the thinking prompt, then reasoning and block as the completion; loss on the completion."""
    sft_example = SftExample(
        example.source, example.proof_identifier, example.step_index, example.goals, example.tactic_block
    )
    match example.reasoning:
        case None:
            return tokenize_example(tokenizer, sft_example)
        case str() as reasoning if example.visible:
            prompt_ids = tokenizer.encode(
                render_prompt(tokenizer, example.goals, visible=True), add_special_tokens=False
            )
            completion = render_visible_completion(reasoning, example.tactic_block)
            completion_ids = tokenizer.encode(completion, add_special_tokens=False)
            return TokenizedExample(sft_example, tuple(prompt_ids + completion_ids), len(prompt_ids))
        case str() as reasoning:
            prompt = render_prompt(
                tokenizer, example.goals, thinking=True, thinking_instruction=example.thinking_instruction
            )
            prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
            completion = render_thinking_completion(reasoning, example.tactic_block)
            completion_ids = tokenizer.encode(completion, add_special_tokens=False)
            return TokenizedExample(sft_example, tuple(prompt_ids + completion_ids), len(prompt_ids))


def interleaved(examples: Sequence[ReasoningExample], seed: str) -> list[ReasoningExample]:
    return sorted(
        examples,
        key=lambda example: stable_fraction(
            f"{example.proof_identifier}#{example.step_index}#{example.reasoning}", f"{seed} order"
        ),
    )


def write_examples(path: Path, examples: Iterable[ReasoningExample]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_examples(path: Path) -> Iterator[ReasoningExample]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            fields["goals"] = tuple(fields["goals"])
            fields["origin"] = ReasoningOrigin(fields["origin"])
            yield ReasoningExample(**fields)
