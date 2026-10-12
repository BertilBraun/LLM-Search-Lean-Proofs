"""Statistics of a reasoning run: outcomes, success rate against reasoning length, by source, selection yield."""

import bisect
import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lean_search.reasoning.dataset import SelectionConfig, select_samples
from lean_search.reasoning.records import ScoredSample, StateRecord, scored_samples
from lean_search.reasoning.reward import RewardConfig, StepOutcome

# Lower bucket edges in reasoning tokens; truncated samples get their own row.
REASONING_LENGTH_EDGES = (0, 1, 32, 64, 128, 192, 256, 384, 512, 768, 1024, 1536)
# Generation caps simulated by cutting the run's samples, up to the run's own cap.
SIMULATED_CAPS = (256, 512, 1024, 2048)
TRUNCATED_BUCKET = "truncated"


@dataclass(frozen=True)
class SampleGroup:
    label: str
    states: int
    samples: int
    success_rate: float
    fully_valid_rate: float
    closed_rate: float
    reference_rate: float
    any_success_rate: float
    mean_generated_tokens: float
    mean_reasoning_tokens: float


@dataclass(frozen=True)
class OutcomeCount:
    outcome: StepOutcome
    samples: int
    share: float


@dataclass(frozen=True)
class CapSimulation:
    cap: int
    success_rate: float
    any_success_rate: float
    tokens_per_sample: float
    tokens_per_success: float
    # Samples that finished but needed more tokens than the cap, so that cap truncates them, and their success rate.
    finished_beyond_cap: int
    finished_beyond_cap_success_rate: float


@dataclass(frozen=True)
class SelectionYield:
    states_with_examples: int
    examples: int
    mean_reasoning_tokens: float
    median_reasoning_tokens: float


@dataclass(frozen=True)
class RunStatistics:
    states: int
    unusable_states: int
    overall: SampleGroup
    outcomes: tuple[OutcomeCount, ...]
    # Among REFERENCE samples: how many reached the next state (1), the one after (2), ...
    reference_steps_advanced: tuple[int, ...]
    generated_tokens_per_success: float
    mean_prompt_tokens: float
    by_reasoning_length: tuple[SampleGroup, ...]
    by_source: tuple[SampleGroup, ...]
    by_sft_exposure: tuple[SampleGroup, ...]
    # Samples whose block was written without the opening fence, which only the reasoning pipeline parses.
    recovered_format: SampleGroup
    caps: tuple[CapSimulation, ...]
    selection: SelectionYield


@dataclass(frozen=True)
class ScoredState:
    record: StateRecord
    samples: tuple[ScoredSample, ...]


def rate(count: float, total: int) -> float:
    return count / total if total else 0.0


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def bucket_label(index: int) -> str:
    lower = REASONING_LENGTH_EDGES[index]
    if index + 1 == len(REASONING_LENGTH_EDGES):
        return f"{lower}+"
    upper = REASONING_LENGTH_EDGES[index + 1] - 1
    return str(lower) if lower == upper else f"{lower}–{upper}"


BUCKET_LABELS = (*(bucket_label(index) for index in range(len(REASONING_LENGTH_EDGES))), TRUNCATED_BUCKET)


def length_bucket(sample: ScoredSample) -> str:
    if sample.outcome == StepOutcome.TRUNCATED:
        return TRUNCATED_BUCKET
    return bucket_label(bisect.bisect_right(REASONING_LENGTH_EDGES, sample.sample.reasoning_tokens) - 1)


def sample_group(label: str, states: Sequence[ScoredState], include: Callable[[ScoredSample], bool]) -> SampleGroup:
    selected_by_state = [[sample for sample in state.samples if include(sample)] for state in states]
    selected_by_state = [samples for samples in selected_by_state if samples]
    samples = [sample for state_samples in selected_by_state for sample in state_samples]
    return SampleGroup(
        label=label,
        states=len(selected_by_state),
        samples=len(samples),
        success_rate=rate(sum(sample.success for sample in samples), len(samples)),
        fully_valid_rate=rate(sum(sample.outcome.fully_applied for sample in samples), len(samples)),
        closed_rate=rate(sum(sample.outcome == StepOutcome.CLOSED for sample in samples), len(samples)),
        reference_rate=rate(sum(sample.outcome == StepOutcome.REFERENCE for sample in samples), len(samples)),
        any_success_rate=rate(
            sum(any(sample.success for sample in state_samples) for state_samples in selected_by_state),
            len(selected_by_state),
        ),
        mean_generated_tokens=mean([sample.sample.generated_tokens for sample in samples]),
        mean_reasoning_tokens=mean([sample.sample.reasoning_tokens for sample in samples]),
    )


def cap_simulation(states: Sequence[ScoredState], cap: int) -> CapSimulation:
    """The run as if every sample had been cut at `cap` generated tokens."""
    samples = [sample for state in states for sample in state.samples]
    successes = sum(sample.success and sample.sample.generated_tokens <= cap for sample in samples)
    tokens = sum(min(sample.sample.generated_tokens, cap) for sample in samples)
    beyond = [
        sample for sample in samples if sample.outcome != StepOutcome.TRUNCATED and sample.sample.generated_tokens > cap
    ]
    return CapSimulation(
        cap=cap,
        success_rate=rate(successes, len(samples)),
        any_success_rate=rate(
            sum(
                any(sample.success and sample.sample.generated_tokens <= cap for sample in state.samples)
                for state in states
            ),
            len(states),
        ),
        tokens_per_sample=rate(tokens, len(samples)),
        tokens_per_success=rate(tokens, successes),
        finished_beyond_cap=len(beyond),
        finished_beyond_cap_success_rate=rate(sum(sample.success for sample in beyond), len(beyond)),
    )


def run_statistics(records: Sequence[StateRecord], reward: RewardConfig, selection: SelectionConfig) -> RunStatistics:
    usable = [ScoredState(record, tuple(scored_samples(record, reward))) for record in records if record.usable]
    samples = [sample for state in usable for sample in state.samples]
    outcome_counts = Counter(sample.outcome for sample in samples)
    advanced = Counter(sample.reference_steps_advanced for sample in samples if sample.outcome == StepOutcome.REFERENCE)
    successes = sum(sample.success for sample in samples)
    selected_by_state = [select_samples(state.record, reward, selection) for state in usable]
    selected = [sample for state_selection in selected_by_state for sample in state_selection]
    selected_lengths = [sample.reasoning_tokens for sample in selected]
    sources = sorted({state.record.sampled.state.source for state in usable})
    return RunStatistics(
        states=len(records),
        unusable_states=len(records) - len(usable),
        overall=sample_group("all", usable, lambda sample: True),
        outcomes=tuple(
            OutcomeCount(outcome, outcome_counts[outcome], rate(outcome_counts[outcome], len(samples)))
            for outcome in StepOutcome
            if outcome_counts[outcome]
        ),
        reference_steps_advanced=tuple(advanced[steps] for steps in range(1, max(advanced, default=0) + 1)),
        generated_tokens_per_success=rate(sum(sample.sample.generated_tokens for sample in samples), successes),
        mean_prompt_tokens=mean([state.record.sampled.prompt_tokens for state in usable]),
        by_reasoning_length=tuple(
            group
            for label in BUCKET_LABELS
            if (
                group := sample_group(label, usable, lambda sample, label=label: length_bucket(sample) == label)
            ).samples
        ),
        by_source=tuple(
            sample_group(
                source,
                [state for state in usable if state.record.sampled.state.source == source],
                lambda sample: True,
            )
            for source in sources
        ),
        by_sft_exposure=tuple(
            group
            for label, seen in (("unseen in SFT", False), ("seen in SFT", True))
            if (
                group := sample_group(
                    label,
                    [state for state in usable if state.record.sampled.state.seen_in_sft == seen],
                    lambda sample: True,
                )
            ).samples
        ),
        recovered_format=sample_group("recovered format", usable, lambda sample: sample.sample.recovered_format),
        caps=tuple(
            cap_simulation(usable, cap)
            for cap in SIMULATED_CAPS
            if cap <= max((state.record.sampled.max_tokens for state in usable), default=0)
        ),
        selection=SelectionYield(
            states_with_examples=sum(bool(state_selection) for state_selection in selected_by_state),
            examples=len(selected),
            mean_reasoning_tokens=mean(selected_lengths),
            median_reasoning_tokens=statistics.median(selected_lengths) if selected_lengths else 0.0,
        ),
    )
