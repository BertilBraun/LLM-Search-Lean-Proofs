"""GRPO training sequences: each recorded policy sample of a group, tokenized with its per-token advantages."""

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lean_search.policy.prompts import END_OF_TURN, ChatTemplate
from lean_search.rl.advantages import (
    AdvantageConfig,
    GroupAdvantages,
    SampleAdvantages,
    group_advantages,
    local_share_of_advantages,
)
from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig
from lean_search.rl.token_credit import CreditMode, TokenSegment, token_credits
from lean_search.search.records import from_json_object, to_json
from lean_search.search.texts import ExpansionTexts, SampledCompletion
from lean_search.training.sft_data import SftExample, TokenizedExample


@dataclass(frozen=True)
class GroupWeightConfig:
    # Groups whose samples differ in G, the global term.
    global_signal_weight: float = 1.0
    # Groups whose samples differ only in the local term.
    local_only_weight: float = 1.0


class PolicyTokenizer(ChatTemplate, Protocol):
    pad_token_id: int

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]: ...


@dataclass(frozen=True)
class PolicySequence:
    problem_name: str
    node_id: int
    edge_id: int
    tokenized: TokenizedExample
    # Per completion token.
    advantages: tuple[float, ...]
    trained: tuple[bool, ...]
    weight: float
    explanation_tokens: int
    block_tokens: int
    masked_tokens: int

    @property
    def token_count(self) -> int:
        return self.tokenized.token_count


@dataclass(frozen=True)
class PolicyDataMetrics:
    groups: int
    groups_with_mixed_rewards: int
    groups_with_global_signal: int
    # Policy samples (multiplicities) in all groups, and the sample-weighted means of the mixed reward's terms.
    samples: int
    mean_reward: float
    mean_global_reward: float
    mean_local_reward: float
    # Of the summed |advantage| of the trained groups, the share from the local term.
    local_advantage_share: float
    sequences: int
    sequences_over_length: int
    # Group samples whose edges have no recorded completion text.
    samples_without_text: int
    mean_explanation_tokens: float
    mean_block_tokens: float
    masked_token_share: float

    @property
    def mixed_reward_share(self) -> float:
        return self.groups_with_mixed_rewards / self.groups if self.groups else 0.0


@dataclass(frozen=True)
class PolicyData:
    sequences: tuple[PolicySequence, ...]
    metrics: PolicyDataMetrics


def write_expansion_texts(path: Path, expansions: Iterable[ExpansionTexts]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for expansion in expansions:
            handle.write(to_json(expansion) + "\n")
            count += 1
    return count


def read_expansion_texts(path: Path) -> Iterator[ExpansionTexts]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield from_json_object(ExpansionTexts, json.loads(line))


def group_weight(advantages: GroupAdvantages, config: GroupWeightConfig) -> float:
    """0 for a group whose samples all earned the same reward, as in the mainstream recipes."""
    if not advantages.has_mixed_rewards:
        return 0.0
    return config.global_signal_weight if advantages.has_global_signal else config.local_only_weight


def completion_offsets(tokenizer: PolicyTokenizer, text: str) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    input_ids = tuple(int(token) for token in encoded["input_ids"])
    offsets = tuple((int(start), int(end)) for start, end in encoded["offset_mapping"])
    return input_ids, offsets


def policy_sequence(
    tokenizer: PolicyTokenizer,
    group: PolicyGroup,
    prompt_ids: Sequence[int],
    completion: SampledCompletion,
    first_failing_tactic: int | None,
    advantages: SampleAdvantages,
    credit_mode: CreditMode,
    weight: float,
) -> PolicySequence:
    text = completion.text + END_OF_TURN if completion.ended_turn else completion.text
    completion_ids, offsets = completion_offsets(tokenizer, text)
    credits = token_credits(offsets, completion.tactic_spans, first_failing_tactic, advantages, credit_mode)
    example = SftExample("grpo", f"{group.problem_name}#{group.node_id}", completion.edge_id, group.goals, "")
    segments = credits.segments
    return PolicySequence(
        problem_name=group.problem_name,
        node_id=group.node_id,
        edge_id=completion.edge_id,
        tokenized=TokenizedExample(example, (*prompt_ids, *completion_ids), len(prompt_ids)),
        advantages=credits.advantages,
        trained=credits.trained,
        weight=weight,
        explanation_tokens=segments.count(TokenSegment.EXPLANATION),
        block_tokens=len(segments) - segments.count(TokenSegment.EXPLANATION),
        masked_tokens=segments.count(TokenSegment.MASKED),
    )


def fits(sequence: PolicySequence, max_prompt_tokens: int, max_completion_tokens: int) -> bool:
    tokenized = sequence.tokenized
    return (
        tokenized.prompt_token_count <= max_prompt_tokens and tokenized.completion_token_count <= max_completion_tokens
    )


def build_policy_data(
    groups: Sequence[PolicyGroup],
    texts: Sequence[ExpansionTexts],
    tokenizer: PolicyTokenizer,
    reward_config: RewardConfig,
    advantage_config: AdvantageConfig,
    credit_mode: CreditMode,
    weights: GroupWeightConfig,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> PolicyData:
    """Sequences of every group with mixed rewards; each recorded completion of a sample's edges is one sequence."""
    texts_by_node = {(expansion.problem_name, expansion.node_id): expansion for expansion in texts}
    sequences: list[PolicySequence] = []
    all_advantages = [group_advantages(group, reward_config, advantage_config) for group in groups]
    trained_advantages: list[GroupAdvantages] = []
    over_length = 0
    without_text = 0
    for group, advantages in zip(groups, all_advantages, strict=True):
        weight = group_weight(advantages, weights)
        if weight == 0:
            continue
        trained_advantages.append(advantages)
        expansion = texts_by_node.get((group.problem_name, group.node_id))
        completions = () if expansion is None else expansion.completions
        prompt_ids = [] if expansion is None else tokenizer.encode(expansion.prompt, add_special_tokens=False)
        for sample, sample_advantages in zip(group.samples, advantages.advantages, strict=True):
            sample_completions = [completion for completion in completions if completion.edge_id in sample.edge_ids]
            if not sample_completions:
                without_text += sample.multiplicity
            for completion in sample_completions:
                sequence = policy_sequence(
                    tokenizer,
                    group,
                    prompt_ids,
                    completion,
                    sample.credit.first_failing_tactic,
                    sample_advantages,
                    credit_mode,
                    weight,
                )
                if fits(sequence, max_prompt_tokens, max_completion_tokens):
                    sequences.append(sequence)
                else:
                    over_length += 1
    metrics = data_metrics(groups, all_advantages, trained_advantages, sequences, over_length, without_text)
    return PolicyData(tuple(sequences), metrics)


def data_metrics(
    groups: Sequence[PolicyGroup],
    all_advantages: Sequence[GroupAdvantages],
    trained_advantages: Sequence[GroupAdvantages],
    sequences: Sequence[PolicySequence],
    over_length: int,
    without_text: int,
) -> PolicyDataMetrics:
    samples = sum(group.sample_count for group in groups)
    rewards = [
        (reward, sample.multiplicity)
        for group, advantages in zip(groups, all_advantages, strict=True)
        for sample, reward in zip(group.samples, advantages.rewards, strict=True)
    ]
    completion_tokens = sum(sequence.tokenized.completion_token_count for sequence in sequences)
    count = max(1, len(sequences))
    return PolicyDataMetrics(
        groups=len(groups),
        groups_with_mixed_rewards=sum(advantages.has_mixed_rewards for advantages in all_advantages),
        groups_with_global_signal=sum(advantages.has_global_signal for advantages in all_advantages),
        samples=samples,
        mean_reward=sum(reward.total * weight for reward, weight in rewards) / max(1, samples),
        mean_global_reward=sum(reward.global_value * weight for reward, weight in rewards) / max(1, samples),
        mean_local_reward=sum(reward.local * weight for reward, weight in rewards) / max(1, samples),
        local_advantage_share=local_share_of_advantages(trained_advantages),
        sequences=len(sequences),
        sequences_over_length=over_length,
        samples_without_text=without_text,
        mean_explanation_tokens=sum(sequence.explanation_tokens for sequence in sequences) / count,
        mean_block_tokens=sum(sequence.block_tokens for sequence in sequences) / count,
        masked_token_share=sum(sequence.masked_tokens for sequence in sequences) / max(1, completion_tokens),
    )
