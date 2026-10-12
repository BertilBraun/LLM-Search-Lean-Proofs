"""Short-reasoning bootstrap: which successes to compress or rationalize, the checked rewrites, and the examples."""

import asyncio
import dataclasses
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lean_search.corpora.tracing import state_before
from lean_search.reasoning.compression import (
    Rewrite,
    RewriteConfig,
    RewriteDefect,
    RewriteMode,
    RewriteRequest,
    SufficiencyCheck,
    SufficiencyConfig,
    SufficiencyItem,
)
from lean_search.reasoning.dataset import (
    ReasoningExample,
    ReasoningOrigin,
    SelectionConfig,
    ordered_successes,
    reasoning_example,
)
from lean_search.reasoning.records import SampleRecord, StateRecord, scored_samples
from lean_search.reasoning.reward import RewardConfig
from lean_search.reasoning.states import ReasoningState


@dataclass(frozen=True)
class ShorteningConfig:
    # Successful reasoning up to this length is kept as it is; longer reasoning needs a sufficient compression.
    max_kept_reasoning_tokens: int = 256
    # Successes per state considered, in the selection's order (distinct blocks first, shortest reasoning first).
    candidates_per_state: int = 3
    rewrite: RewriteConfig = field(default_factory=RewriteConfig)
    sufficiency: SufficiencyConfig = field(default_factory=SufficiencyConfig)
    # Runs on the same states (usually without thinking) whose successful steps are rationalized for the states
    # without any thinking success; empty turns rationalization off.
    rationalize_runs: tuple[str, ...] = ()


class Rewriter(Protocol):
    async def rewrite(self, request: RewriteRequest, mode: RewriteMode) -> tuple[Rewrite, ...]: ...


class Checker(Protocol):
    async def check(self, items: Sequence[SufficiencyItem]) -> list[SufficiencyCheck]: ...


@dataclass(frozen=True)
class CheckedRewrite:
    rewrite: Rewrite
    # None when the rewrite was defective and never checked.
    check: SufficiencyCheck | None

    @property
    def sufficient(self) -> bool:
        return self.check is not None and self.check.sufficient


@dataclass(frozen=True)
class ShortenedReasoning:
    state_identifier: str
    mode: RewriteMode
    # The successful sample of the state's record (the thinking run's, or a rationalized run's) the rewrites are for.
    sample_index: int
    tactic_block: str
    # The sampled trace and its tokens; empty and 0 when rationalizing.
    original_reasoning: str
    original_tokens: int
    rewrites: tuple[CheckedRewrite, ...]

    def shortest_sufficient(self) -> Rewrite | None:
        sufficient = [checked.rewrite for checked in self.rewrites if checked.sufficient]
        return min(sufficient, key=lambda rewrite: rewrite.tokens, default=None)


@dataclass(frozen=True)
class ShorteningTarget:
    state: ReasoningState
    mode: RewriteMode
    sample: SampleRecord

    @property
    def request(self) -> RewriteRequest:
        assert self.sample.tactic_block is not None
        reasoning = self.sample.reasoning if self.mode == RewriteMode.COMPRESS else ""
        return RewriteRequest(self.state.goals, self.sample.tactic_block, reasoning)


def compression_targets(
    record: StateRecord, reward: RewardConfig, selection: SelectionConfig, config: ShorteningConfig
) -> list[SampleRecord]:
    considered = ordered_successes(record, reward, selection)[: config.candidates_per_state]
    return [sample for sample in considered if sample.reasoning_tokens > config.max_kept_reasoning_tokens]


def rationalization_targets(
    record: StateRecord,
    other: StateRecord,
    reward: RewardConfig,
    selection: SelectionConfig,
    config: ShorteningConfig,
) -> list[SampleRecord]:
    """Distinct successful steps of another run on the state, when the thinking run has no usable success."""
    if ordered_successes(record, reward, selection) or not other.usable:
        return []
    successes = [scored.sample for scored in scored_samples(other, reward) if scored.success]
    distinct = {sample.tactic_block: sample for sample in reversed(successes)}
    return sorted(distinct.values(), key=lambda sample: sample.index)[: config.candidates_per_state]


def shortening_targets(
    records: Sequence[StateRecord],
    others: Mapping[str, StateRecord],
    reward: RewardConfig,
    selection: SelectionConfig,
    config: ShorteningConfig,
) -> list[ShorteningTarget]:
    targets: list[ShorteningTarget] = []
    for record in records:
        if not record.usable:
            continue
        state = record.sampled.state
        targets += [
            ShorteningTarget(state, RewriteMode.COMPRESS, sample)
            for sample in compression_targets(record, reward, selection, config)
        ]
        if (other := others.get(state.identifier)) is not None:
            targets += [
                ShorteningTarget(state, RewriteMode.RATIONALIZE, sample)
                for sample in rationalization_targets(record, other, reward, selection, config)
            ]
    return targets


async def shorten(
    targets: Sequence[ShorteningTarget], rewriter: Rewriter, checker: Checker
) -> list[ShortenedReasoning]:
    """Rewrites every target, then checks every well-formed rewrite on the target's state in one batch."""
    rewrites = await asyncio.gather(*(rewriter.rewrite(target.request, target.mode) for target in targets))
    pending = [
        (target_index, rewrite_index)
        for target_index, target_rewrites in enumerate(rewrites)
        for rewrite_index, rewrite in enumerate(target_rewrites)
        if rewrite.defect is None
    ]
    items = [
        SufficiencyItem(
            state_before(targets[target_index].state.step),
            targets[target_index].state.reference_goal_keys,
            rewrites[target_index][rewrite_index].text,
        )
        for target_index, rewrite_index in pending
    ]
    checks = dict(zip(pending, await checker.check(items), strict=True))
    return [
        ShortenedReasoning(
            state_identifier=target.state.identifier,
            mode=target.mode,
            sample_index=target.sample.index,
            tactic_block=target.request.tactic_block,
            original_reasoning=target.request.reasoning,
            original_tokens=target.sample.reasoning_tokens if target.mode == RewriteMode.COMPRESS else 0,
            rewrites=tuple(
                CheckedRewrite(rewrite, checks.get((target_index, rewrite_index)))
                for rewrite_index, rewrite in enumerate(rewrites[target_index])
            ),
        )
        for target_index, target in enumerate(targets)
    ]


def short_reasoning_examples(
    record: StateRecord,
    shortened: Sequence[ShortenedReasoning],
    reward: RewardConfig,
    selection: SelectionConfig,
    max_kept_reasoning_tokens: int,
) -> list[ReasoningExample]:
    """Successes in selection order with short or sufficiently compressed reasoning; else rationalized steps."""
    compressed = {
        entry.sample_index: entry.shortest_sufficient() for entry in shortened if entry.mode == RewriteMode.COMPRESS
    }
    examples: list[ReasoningExample] = []
    for sample in ordered_successes(record, reward, selection):
        if len(examples) == selection.max_per_state:
            return examples
        if sample.reasoning_tokens <= max_kept_reasoning_tokens:
            examples.append(reasoning_example(record.sampled, sample))
        elif (rewrite := compressed.get(sample.index)) is not None:
            example = reasoning_example(record.sampled, sample)
            examples.append(dataclasses.replace(example, reasoning=rewrite.text, origin=ReasoningOrigin.COMPRESSED))
    if examples:
        return examples
    step = record.sampled.state.step
    rationalized = [
        ReasoningExample(
            step.source,
            step.proof_identifier,
            step.step_index,
            record.sampled.state.goals,
            entry.tactic_block,
            rewrite.text,
            record.sampled.thinking_instruction,
            ReasoningOrigin.RATIONALIZED,
        )
        for entry in shortened
        if entry.mode == RewriteMode.RATIONALIZE and (rewrite := entry.shortest_sufficient()) is not None
    ]
    return rationalized[: selection.max_per_state]


@dataclass(frozen=True)
class DefectCount:
    defect: RewriteDefect
    rewrites: int


@dataclass(frozen=True)
class ShorteningStatistics:
    mode: RewriteMode
    targets: int
    rewrites: int
    defects: tuple[DefectCount, ...]
    checked_rewrites: int
    sufficient_rewrites: int
    # Targets with at least one sufficient rewrite.
    pass_rate: float
    # Successful samples out of the k sampled after each checked rewrite.
    check_success_rate: float
    mean_original_tokens: float
    # Of the shortest sufficient rewrite of each passing target.
    mean_shortened_tokens: float
    median_compression_ratio: float


def shortening_statistics(
    shortened: Sequence[ShortenedReasoning], mode: RewriteMode, sample_count: int
) -> ShorteningStatistics:
    entries = [entry for entry in shortened if entry.mode == mode]
    rewrites = [checked for entry in entries for checked in entry.rewrites]
    checked = [entry.check for entry in rewrites if entry.check is not None]
    passing = [(entry, rewrite) for entry in entries if (rewrite := entry.shortest_sufficient()) is not None]
    defects = Counter(entry.rewrite.defect for entry in rewrites if entry.rewrite.defect is not None)
    ratios = [rewrite.tokens / entry.original_tokens for entry, rewrite in passing if entry.original_tokens]
    return ShorteningStatistics(
        mode=mode,
        targets=len(entries),
        rewrites=len(rewrites),
        defects=tuple(DefectCount(defect, defects[defect]) for defect in RewriteDefect if defects[defect]),
        checked_rewrites=len(checked),
        sufficient_rewrites=sum(check.sufficient for check in checked),
        pass_rate=len(passing) / len(entries) if entries else 0.0,
        check_success_rate=(
            sum(check.successes for check in checked) / (len(checked) * sample_count) if checked else 0.0
        ),
        mean_original_tokens=statistics.fmean([entry.original_tokens for entry in entries]) if entries else 0.0,
        mean_shortened_tokens=statistics.fmean([rewrite.tokens for _, rewrite in passing]) if passing else 0.0,
        median_compression_ratio=statistics.median(ratios) if ratios else 0.0,
    )
