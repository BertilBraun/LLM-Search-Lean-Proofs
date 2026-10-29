"""GRPO training sequences: each recorded completion of a group sample, as sampled, with its per-token advantages."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from lean_search.policy.prompts import END_OF_TURN, ChatTemplate
from lean_search.rl.advantages import (
    CreditMode,
    GroupAdvantages,
    SampleAdvantages,
    group_advantages,
    local_share_of_advantages,
)
from lean_search.rl.grpo_groups import GroupSample, PolicyGroup
from lean_search.rl.token_credit import (
    TokenSegment,
    inserted_token_indices,
    sampled_token_offsets,
    token_credits,
)
from lean_search.search.tactic_labels import TacticLabelCounts
from lean_search.search.texts import ExpansionTexts, SampledCompletion
from lean_search.training.sft_data import SftExample, TokenizedExample


class PolicyTokenizer(ChatTemplate, Protocol):
    pad_token_id: int

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str: ...

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]: ...


@dataclass(frozen=True)
class PolicyDataConfig:
    credit: CreditMode = CreditMode.PER_TACTIC
    # The sampling temperature of records written before it was kept.
    default_temperature: float = 0.8


@dataclass(frozen=True)
class PolicySequence:
    problem_name: str
    node_id: int
    edge_id: int
    tokenized: TokenizedExample
    # Per completion token.
    advantages: tuple[float, ...]
    trained: tuple[bool, ...]
    # The sampler's log-probability per completion token (None where inserted); empty when re-tokenized.
    sampler_log_probabilities: tuple[float | None, ...]
    temperature: float
    # The published policy version that sampled it; None outside the loop and in older records.
    policy_version: int | None
    # The answer was forced at the token cap (the harness inserted the opening).
    forced: bool
    # Records without token ids: the text tokenized again.
    retokenized: bool
    segments: tuple[TokenSegment, ...]

    @property
    def token_count(self) -> int:
        return self.tokenized.token_count

    def segment_tokens(self, segment: TokenSegment) -> int:
        return self.segments.count(segment)


@dataclass(frozen=True)
class PolicyDataMetrics:
    groups: int
    # Groups with a non-zero advantage, the only ones trained.
    groups_trained: int
    # Policy samples (multiplicities) in all groups.
    samples: int
    # Tactics of the trained groups' samples by credit label, sample-weighted.
    tactics: TacticLabelCounts
    # Sample-weighted means of (1 − λ) · G and λ · L over the known tactics of all groups.
    mean_global_reward: float
    mean_local_reward: float
    # Of the summed |tactic advantage| of the trained groups, the share from the local term.
    local_advantage_share: float
    sequences: int
    # Group samples whose edges have no recorded completion text.
    samples_without_text: int
    retokenized_sequences: int
    # Recorded tokens that did not decode to the recorded text: trained with sequence-level credit.
    token_mismatch_sequences: int
    forced_sequences: int
    mean_explanation_tokens: float
    mean_tactics_per_sample: float
    untrained_token_share: float


@dataclass(frozen=True)
class PolicyData:
    sequences: tuple[PolicySequence, ...]
    metrics: PolicyDataMetrics


@dataclass(frozen=True)
class SamplerAgreement:
    """The trainer's log-probabilities before the first update against the sampler's recorded ones."""

    tokens: int
    # Means over the tokens of trainer minus sampler, of its absolute value, and the k3 KL(sampler || trainer).
    mean_difference: float
    mean_absolute_difference: float
    kl_sampler_to_trainer: float


@dataclass(frozen=True)
class VersionSamplerAgreement:
    # The published policy version that sampled the tokens; None where it was not recorded.
    policy_version: int | None
    agreement: SamplerAgreement


@dataclass(frozen=True)
class TreeGroups:
    """One tree's groups and its expansions' texts: node and edge ids identify them only within the tree."""

    groups: tuple[PolicyGroup, ...]
    texts: tuple[ExpansionTexts, ...]


@dataclass(frozen=True)
class CompletionTokens:
    token_ids: tuple[int, ...]
    # None when the recorded tokens do not decode to the recorded text.
    offsets: tuple[tuple[int, int], ...] | None
    inserted: frozenset[int]
    sampler_log_probabilities: tuple[float | None, ...]
    retokenized: bool


def completion_tokens(tokenizer: PolicyTokenizer, completion: SampledCompletion) -> CompletionTokens:
    """The recorded tokens; records written before tokens were kept tokenize the text again."""
    tokens = completion.tokens
    if tokens.token_ids:
        offsets = sampled_token_offsets(tokenizer, completion)
        return CompletionTokens(
            tokens.token_ids, offsets, inserted_token_indices(completion), tokens.log_probabilities, False
        )
    text = completion.text + END_OF_TURN if completion.ended_turn else completion.text
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    return CompletionTokens(
        tuple(int(token) for token in encoded["input_ids"]),
        tuple((int(start), int(end)) for start, end in encoded["offset_mapping"]),
        frozenset(),
        (),
        True,
    )


def policy_sequence(
    tokenizer: PolicyTokenizer,
    group: PolicyGroup,
    expansion: ExpansionTexts,
    prompt_ids: Sequence[int],
    completion: SampledCompletion,
    temperature: float,
    advantages: SampleAdvantages,
    credit: CreditMode,
) -> tuple[PolicySequence, bool]:
    """The sequence, and whether its tokens failed to decode to its text (then all get the sequence credit)."""
    tokens = completion_tokens(tokenizer, completion)
    offsets = tokens.offsets
    mismatch = offsets is None
    if offsets is None:
        offsets = tuple((0, 0) for _ in tokens.token_ids)
    spans = () if mismatch else completion.tactic_spans
    credits = token_credits(offsets, spans, tokens.inserted, advantages, credit)
    example = SftExample("grpo", f"{group.problem_name}#{group.node_id}", completion.edge_id, group.goals, "")
    sequence = PolicySequence(
        problem_name=group.problem_name,
        node_id=group.node_id,
        edge_id=completion.edge_id,
        tokenized=TokenizedExample(example, (*prompt_ids, *tokens.token_ids), len(prompt_ids)),
        advantages=credits.advantages,
        trained=credits.trained,
        sampler_log_probabilities=tokens.sampler_log_probabilities,
        temperature=temperature,
        policy_version=expansion.policy_version,
        forced=bool(tokens.inserted),
        retokenized=tokens.retokenized,
        segments=credits.segments,
    )
    return sequence, mismatch


def build_policy_data(trees: Sequence[TreeGroups], tokenizer: PolicyTokenizer, config: PolicyDataConfig) -> PolicyData:
    """Every recorded completion of a group with a signal is one sequence; groups whose advantages are all 0 drop."""
    sequences: list[PolicySequence] = []
    trained_groups: list[tuple[PolicyGroup, GroupAdvantages]] = []
    without_text = 0
    mismatches = 0
    for tree in trees:
        texts_by_node = {expansion.node_id: expansion for expansion in tree.texts}
        for group in tree.groups:
            advantages = group_advantages(group)
            if not advantages.has_signal(config.credit):
                continue
            trained_groups.append((group, advantages))
            expansion = texts_by_node.get(group.node_id)
            if expansion is None:
                without_text += group.sample_count
                continue
            prompt_ids = tokenizer.encode(expansion.prompt, add_special_tokens=False)
            temperature = config.default_temperature if expansion.temperature is None else expansion.temperature
            for sample, sample_advantages in zip(group.samples, advantages.samples, strict=True):
                completions = [item for item in expansion.completions if item.edge_id in sample.edge_ids]
                if not completions:
                    without_text += sample.multiplicity
                for completion in completions:
                    sequence, mismatch = policy_sequence(
                        tokenizer,
                        group,
                        expansion,
                        prompt_ids,
                        completion,
                        temperature,
                        sample_advantages,
                        config.credit,
                    )
                    sequences.append(sequence)
                    mismatches += mismatch
    groups = [group for tree in trees for group in tree.groups]
    metrics = data_metrics(groups, trained_groups, sequences, without_text, mismatches)
    return PolicyData(tuple(sequences), metrics)


def weighted_samples(groups: Iterable[PolicyGroup]) -> list[GroupSample]:
    return [sample for group in groups for sample in group.samples for _ in range(sample.multiplicity)]


def data_metrics(
    groups: Sequence[PolicyGroup],
    trained_groups: Sequence[tuple[PolicyGroup, GroupAdvantages]],
    sequences: Sequence[PolicySequence],
    without_text: int,
    mismatches: int,
) -> PolicyDataMetrics:
    samples = weighted_samples(groups)
    known = [parts for sample in samples for parts in sample.known]
    trained_samples = weighted_samples(group for group, _ in trained_groups)
    completion_tokens_total = sum(sequence.tokenized.completion_token_count for sequence in sequences)
    untrained = sum(
        not trained
        for sequence in sequences
        for trained, segment in zip(sequence.trained, sequence.segments, strict=True)
        if segment != TokenSegment.INSERTED
    )
    inserted = sum(sequence.segment_tokens(TokenSegment.INSERTED) for sequence in sequences)
    count = max(1, len(sequences))
    return PolicyDataMetrics(
        groups=len(groups),
        groups_trained=len(trained_groups),
        samples=len(samples),
        tactics=TacticLabelCounts.of(tactic.label for sample in trained_samples for tactic in sample.tactics),
        mean_global_reward=sum(parts.global_part for parts in known) / max(1, len(known)),
        mean_local_reward=sum(parts.local_part for parts in known) / max(1, len(known)),
        local_advantage_share=local_share_of_advantages([advantages for _, advantages in trained_groups]),
        sequences=len(sequences),
        samples_without_text=without_text,
        retokenized_sequences=sum(sequence.retokenized for sequence in sequences),
        token_mismatch_sequences=mismatches,
        forced_sequences=sum(sequence.forced for sequence in sequences),
        mean_explanation_tokens=sum(sequence.segment_tokens(TokenSegment.EXPLANATION) for sequence in sequences)
        / count,
        mean_tactics_per_sample=sum(len(sample.tactics) for sample in trained_samples) / max(1, len(trained_samples)),
        untrained_token_share=untrained / max(1, completion_tokens_total - inserted),
    )
