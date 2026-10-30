"""Search variants on the held-out states (experiments/search_variants.py): per state and variant what one expansion
gives the search, each variant paired per state with its reference variants, the bootstrap over states.

A variant changes the loop's search template (temperature, the feedback round, the failed automation in the prompt,
name repair, the sweep first) and runs the loop's held-out evaluation with it. The primary metrics are per state: at
least one successful sample (closed, or on the reference proof's next or a later state), distinct new states and
distinct successful states, each also per generated token. Pooled per-sample success is secondary: a feedback round
adds samples only at hard states, which drags a pooled rate down even when it rescues them.

Samples a variant asked for but never ran (its state ran out of the 120 s cap, e.g. in the sweep before the request)
count as failures. A sample whose names the search repaired counts by its own failed run; the repair's edge (or, in
trees written before 2026-10-31, the repaired policy edge) counts apart, in `repaired_*`.
"""

import dataclasses
import math
import re
import tomllib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np

from lean_search.policy.config import FeedbackConfig
from lean_search.rl.loop import LoopProgress, PhaseStage
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_models import evaluation_run_config, run_config_text
from lean_search.rl.search_options import SearchOptions, with_search_options, without_search_options
from lean_search.rl.single_step import RootSample, StateProblem, root_samples, single_step_run_config
from lean_search.search import RunConfig, TreeRecord
from lean_search.search.config import parse_run_config
from lean_search.search.graph_labels import GoalKey
from lean_search.search.records import from_json_object
from lean_search.search.search import NameRepairConfig
from lean_search.search.tree import EdgeOutcome, Failure, FailureKind, StepSource

VARIANT_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
REPAIR_SOURCES = frozenset({StepSource.POLICY, StepSource.REPAIR})
TOKENS_PER_UNIT = 1000
# First-round new states, the last stratum open-ended.
FEEDBACK_STRATA = 4


@dataclass(frozen=True)
class SearchVariant:
    # The variant's directory name.
    name: str
    # None keeps the template's.
    temperature: float | None = None
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    failed_automation_in_prompt: bool = False
    name_repair: NameRepairConfig = field(default_factory=NameRepairConfig)
    # The sweep runs first, without overlap (failed_automation_in_prompt implies it): its control.
    sweep_first: bool = False
    # Variants it is paired with besides the config's baseline: its proper controls.
    compared_with: tuple[str, ...] = ()

    @property
    def options(self) -> SearchOptions:
        return SearchOptions(self.temperature, self.feedback, self.failed_automation_in_prompt, self.name_repair)


@dataclass(frozen=True)
class SearchVariantsConfig:
    # Results under $LEAN_SEARCH_RUNS/<name>/v<served policy version>/<variant>/.
    name: str
    variants: tuple[SearchVariant, ...]
    baseline: str = "baseline"
    # A second run with the baseline's settings: its difference to the baseline is the noise floor; "" none.
    second_baseline: str = ""
    bootstrap_samples: int = 2000
    # The family-wise level of the Holm-corrected comparisons is 1 - confidence; the intervals are per comparison.
    confidence: float = 0.95
    seed: int = 0
    # Every variant searches a chunk of states before the next chunk starts.
    chunk_states: int = 64

    def variant(self, name: str) -> SearchVariant:
        (variant,) = (variant for variant in self.variants if variant.name == name)
        return variant


def parse_search_variants_config(text: str) -> SearchVariantsConfig:
    config = from_json_object(SearchVariantsConfig, tomllib.loads(text))
    names = [variant.name for variant in config.variants]
    if len(set(names)) != len(names) or not all(VARIANT_NAME.fullmatch(name) for name in names):
        raise ValueError(f"Variant names must be distinct and usable as directory names: {names}")
    if config.baseline not in names:
        raise ValueError(f"The baseline {config.baseline!r} is not a variant.")
    if config.second_baseline:
        if config.second_baseline not in names:
            raise ValueError(f"The second baseline {config.second_baseline!r} is not a variant.")
        settings = dataclasses.replace(config.variant(config.second_baseline), name=config.baseline)
        if settings != config.variant(config.baseline):
            raise ValueError("The second baseline must have the baseline's settings.")
    unknown = {name for variant in config.variants for name in variant.compared_with} - set(names)
    if unknown:
        raise ValueError(f"compared_with names unknown variants: {sorted(unknown)}")
    if config.bootstrap_samples < 1 or not 0 < config.confidence < 1 or config.chunk_states < 1:
        raise ValueError("bootstrap_samples and chunk_states must be positive and confidence in (0, 1).")
    return config


def load_search_variants_config(path: Path) -> SearchVariantsConfig:
    return parse_search_variants_config(path.read_text(encoding="utf-8"))


def variant_run_config(template: RunConfig, variant: SearchVariant, target: EvaluationTarget) -> RunConfig:
    """The loop's held-out evaluation of the template (its options off) with the variant's settings; validated like a
    config file."""
    changed = with_search_options(without_search_options(template), variant.options)
    single_step = single_step_run_config(evaluation_run_config(changed, target), variant.sweep_first)
    return parse_run_config(run_config_text(single_step))


@dataclass(frozen=True)
class ServedVersion:
    """The loop's phase while it samples, and the version its servers serve then."""

    phase: int
    version: int


def served_version(progress: LoopProgress, current_version: int) -> ServedVersion | None:
    """None unless the loop samples. From its pause on the servers may already answer with the next version (woken
    with the merges in host memory) while `current` still names the old one; the phase changes before it samples
    again, so a tree whose searches began and ended under the same ServedVersion had one version."""
    if progress.stage != PhaseStage.SAMPLING:
        return None
    return ServedVersion(progress.phase, current_version)


def interleaved_chunks(states: Sequence[StateProblem], chunk_states: int) -> list[list[StateProblem]]:
    """The states in chunks that every variant searches before the next starts, so drift in the loop's load hits all
    variants alike and a stopped run leaves them balanced."""
    return [list(states[start : start + chunk_states]) for start in range(0, len(states), chunk_states)]


class ErrorCategory(StrEnum):
    UNKNOWN_IDENTIFIER = "unknown_identifier"
    SYNTAX = "syntax"
    TYPE_MISMATCH = "type_mismatch"
    LINARITH = "linarith"
    OMEGA = "omega"
    SIMP_NO_PROGRESS = "simp_no_progress"
    REWRITE_PATTERN = "rewrite_pattern"
    UNSOLVED_GOALS = "unsolved_goals"
    TIMEOUT = "timeout"
    FORBIDDEN = "forbidden"
    OTHER = "other"


# Lean's messages, lower-cased, in the order they are tried.
ERROR_MESSAGES = (
    (ErrorCategory.UNKNOWN_IDENTIFIER, re.compile(r"unknown (?:identifier|constant)")),
    (ErrorCategory.SYNTAX, re.compile(r"unexpected (?:token|identifier|end of input)")),
    (ErrorCategory.TYPE_MISMATCH, re.compile(r"type mismatch")),
    (ErrorCategory.LINARITH, re.compile(r"linarith failed")),
    (ErrorCategory.OMEGA, re.compile(r"omega could not prove")),
    (ErrorCategory.SIMP_NO_PROGRESS, re.compile(r"simp(?:_all)? made no progress")),
    (ErrorCategory.REWRITE_PATTERN, re.compile(r"did not find instance of the pattern|motive is not type correct")),
    (ErrorCategory.UNSOLVED_GOALS, re.compile(r"unsolved goals")),
)


def error_category(failure: Failure) -> ErrorCategory:
    match failure.kind:
        case FailureKind.UNKNOWN_IDENTIFIER:
            return ErrorCategory.UNKNOWN_IDENTIFIER
        case FailureKind.HEARTBEAT_TIMEOUT | FailureKind.WALL_CLOCK_TIMEOUT:
            return ErrorCategory.TIMEOUT
        case FailureKind.FORBIDDEN:
            return ErrorCategory.FORBIDDEN
        case _:
            message = failure.message.lower()
            return next(
                (category for category, pattern in ERROR_MESSAGES if pattern.search(message)), ErrorCategory.OTHER
            )


@dataclass(frozen=True)
class ErrorCounts:
    """Samples ending in a Lean error (no state reached), by Lean's message."""

    unknown_identifier: int = 0
    syntax: int = 0
    type_mismatch: int = 0
    linarith: int = 0
    omega: int = 0
    simp_no_progress: int = 0
    rewrite_pattern: int = 0
    unsolved_goals: int = 0
    timeout: int = 0
    forbidden: int = 0
    other: int = 0

    def __add__(self, other: "ErrorCounts") -> "ErrorCounts":
        return ErrorCounts(
            *(mine + theirs for mine, theirs in zip(dataclasses.astuple(self), dataclasses.astuple(other), strict=True))
        )

    @property
    def total(self) -> int:
        return sum(dataclasses.astuple(self))


class SampleOutcome(StrEnum):
    NEW_STATE = "new_state"
    EXISTING_STATE = "existing_state"
    LEAN_ERROR = "lean_error"
    REPEATED = "repeated"
    UNPARSED = "unparsed"


@dataclass(frozen=True)
class SampleOutcomes:
    """Policy samples by what their block did (infrastructure failures left out)."""

    new_state: int = 0
    existing_state: int = 0
    lean_error: int = 0
    # The same block as an earlier sample of the expansion with another prompt (the feedback round).
    repeated: int = 0
    unparsed: int = 0

    def __add__(self, other: "SampleOutcomes") -> "SampleOutcomes":
        return SampleOutcomes(
            *(mine + theirs for mine, theirs in zip(dataclasses.astuple(self), dataclasses.astuple(other), strict=True))
        )

    @property
    def total(self) -> int:
        return sum(dataclasses.astuple(self))


def sample_outcome(outcome: EdgeOutcome, failure: Failure | None) -> SampleOutcome:
    match outcome:
        case EdgeOutcome.CHILD:
            return SampleOutcome.NEW_STATE
        case EdgeOutcome.DUPLICATE:
            return SampleOutcome.EXISTING_STATE
        case EdgeOutcome.REPEATED:
            return SampleOutcome.REPEATED
        case _ if failure is not None and failure.kind == FailureKind.UNPARSED:
            return SampleOutcome.UNPARSED
        case _:
            return SampleOutcome.LEAN_ERROR


def outcome_and_error(sample: RootSample) -> tuple[SampleOutcome, ErrorCategory | None]:
    """A repaired policy edge of an older record failed on its unknown names before its repair ran."""
    if sample.executed.repaired:
        return SampleOutcome.LEAN_ERROR, ErrorCategory.UNKNOWN_IDENTIFIER
    outcome = sample_outcome(sample.edge.outcome, sample.executed.failure)
    failure = sample.executed.failure
    error = error_category(failure) if outcome == SampleOutcome.LEAN_ERROR and failure is not None else None
    return outcome, error


@dataclass(frozen=True)
class RequestedSamples:
    """What the variant's run config asks for per state: the first request's samples, and the feedback round's."""

    first_round: int
    feedback: int


def requested_samples(config: RunConfig) -> RequestedSamples:
    feedback = config.policy.feedback
    return RequestedSamples(config.policy.sample_count, feedback.sample_count if feedback.enabled else 0)


@dataclass(frozen=True)
class StateResult:
    name: str
    # Recorded policy samples (infrastructure failures left out), and those asked for but never run.
    samples: int
    cut_off_samples: int
    successes: int
    # Samples whose block ran completely.
    valid: int
    # At least one successful sample; distinct new states the samples reached, and distinct successful ones.
    solved: bool
    children: int
    successful_children: int
    # The same of the first request alone (the feedback round's counterfactual "off").
    first_round_samples: int
    first_round_cut_off: int
    first_round_successes: int
    first_round_solved: bool
    first_round_children: int
    first_round_successful_children: int
    feedback_fired: bool
    feedback_samples: int
    feedback_successes: int
    feedback_generated_tokens: int
    # Repairs of the policy's samples, those that succeeded, and whether the state is solved counting them.
    repaired_samples: int
    repaired_successes: int
    solved_with_repairs: bool
    outcomes: SampleOutcomes
    errors: ErrorCounts
    prompt_tokens: int
    generated_tokens: int
    lean_seconds: float
    # The automation sweep's share of the Lean seconds (variants that run it first).
    sweep_lean_seconds: float
    wall_seconds: float

    @property
    def denominator(self) -> int:
        return self.samples + self.cut_off_samples

    @property
    def first_round_generated_tokens(self) -> int:
        return self.generated_tokens - self.feedback_generated_tokens


def own(sample: RootSample) -> bool:
    """A sample judged by its own run: not a repair, nor a repaired policy edge of an older record."""
    return sample.edge.source == StepSource.POLICY and not sample.executed.repaired


def distinct(samples: Sequence[RootSample], successful: bool = False) -> set[GoalKey]:
    return {
        sample.reached
        for sample in samples
        if own(sample) and sample.reached is not None and (sample.success or not successful)
    }


def state_result(
    name: str, record: TreeRecord, reference_keys: frozenset[GoalKey], requested: RequestedSamples
) -> StateResult:
    every = root_samples(record, reference_keys, REPAIR_SOURCES)
    samples = [sample for sample in every if sample.edge.source == StepSource.POLICY]
    first = [sample for sample in samples if not sample.edge.feedback]
    feedback = [sample for sample in samples if sample.edge.feedback]
    repaired = [sample for sample in every if sample.executed.repaired]
    outcomes: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    for sample in samples:
        outcome, error = outcome_and_error(sample)
        outcomes[outcome.value] += sample.sample_count
        if error is not None:
            errors[error.value] += sample.sample_count
    root_policy = [edge for edge in record.edges if edge.parent_id == 0 and edge.source == StepSource.POLICY]
    feedback_texts = [texts for texts in record.expansions if texts.node_id == 0 and texts.feedback]
    fired = bool(feedback_texts) or any(edge.feedback for edge in root_policy)
    # Infrastructure failures ran (and are left out of the samples), so they are not cut off.
    first_ran = sum(edge.sample_count for edge in root_policy if not edge.feedback)
    feedback_ran = sum(edge.sample_count for edge in root_policy if edge.feedback)
    first_cut_off = max(0, requested.first_round - first_ran)
    feedback_cut_off = max(0, requested.feedback - feedback_ran) if fired else 0
    accounting = record.result.accounting

    def count(chosen: Sequence[RootSample], successful: bool = False) -> int:
        return sum(sample.sample_count for sample in chosen if own(sample) and (sample.success or not successful))

    return StateResult(
        name=name,
        samples=sum(sample.sample_count for sample in samples),
        cut_off_samples=first_cut_off + feedback_cut_off,
        successes=count(samples, successful=True),
        valid=sum(sample.sample_count for sample in samples if own(sample) and sample.valid),
        solved=count(samples, successful=True) > 0,
        children=len(distinct(samples)),
        successful_children=len(distinct(samples, successful=True)),
        first_round_samples=sum(sample.sample_count for sample in first),
        first_round_cut_off=first_cut_off,
        first_round_successes=count(first, successful=True),
        first_round_solved=count(first, successful=True) > 0,
        first_round_children=len(distinct(first)),
        first_round_successful_children=len(distinct(first, successful=True)),
        feedback_fired=fired,
        feedback_samples=sum(sample.sample_count for sample in feedback),
        feedback_successes=count(feedback, successful=True),
        feedback_generated_tokens=sum(
            len(completion.tokens.token_ids) for texts in feedback_texts for completion in texts.completions
        ),
        repaired_samples=sum(sample.sample_count for sample in repaired),
        repaired_successes=sum(sample.sample_count for sample in repaired if sample.success),
        solved_with_repairs=any(sample.success for sample in every),
        outcomes=SampleOutcomes(**outcomes),
        errors=ErrorCounts(**errors),
        prompt_tokens=accounting.prompt_tokens,
        generated_tokens=accounting.generated_tokens,
        lean_seconds=accounting.lean_seconds,
        sweep_lean_seconds=sum(
            edge.lean_seconds for edge in record.edges if edge.parent_id == 0 and edge.source == StepSource.AUTOMATION
        ),
        wall_seconds=accounting.wall_seconds,
    )


def rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


@dataclass(frozen=True)
class Metric:
    name: str
    value: Callable[[StateResult], float]
    # Per 1000 generated tokens (a ratio of sums over the states); else the mean over the states.
    per_token: bool = False


def per_token(metric: Metric) -> Metric:
    return Metric(f"{metric.name} per 1k tokens", metric.value, per_token=True)


PER_STATE_METRICS = (
    Metric("solved", lambda result: float(result.solved)),
    Metric("children", lambda result: float(result.children)),
    Metric("successful children", lambda result: float(result.successful_children)),
)
PRIMARY_METRICS = (*PER_STATE_METRICS, *(per_token(metric) for metric in PER_STATE_METRICS))


def metric_value(metric: Metric, results: Sequence[StateResult]) -> float:
    values = [metric.value(result) for result in results]
    if metric.per_token:
        return TOKENS_PER_UNIT * rate(sum(values), sum(result.generated_tokens for result in results))
    return mean(values)


@dataclass(frozen=True)
class VariantSummary:
    variant: str
    temperature: float
    states: int
    # Primary, per state.
    solved: float
    mean_children: float
    mean_successful_children: float
    solved_per_1k_tokens: float
    children_per_1k_tokens: float
    successful_children_per_1k_tokens: float
    # Secondary: pooled over samples, those cut off counted as failures.
    samples: int
    cut_off_samples: int
    sample_success_rate: float
    first_round_sample_success_rate: float
    valid_rate: float
    feedback_fired: int
    repaired_samples: int
    repaired_successes: int
    outcomes: SampleOutcomes
    errors: ErrorCounts
    mean_prompt_tokens: float
    mean_generated_tokens: float
    mean_lean_seconds: float
    mean_sweep_lean_seconds: float
    mean_wall_seconds: float
    p90_wall_seconds: float


def variant_summary(variant: str, temperature: float, results: Sequence[StateResult]) -> VariantSummary:
    first_round_denominator = sum(result.first_round_samples + result.first_round_cut_off for result in results)
    values = {metric.name: metric_value(metric, results) for metric in PRIMARY_METRICS}
    return VariantSummary(
        variant=variant,
        temperature=temperature,
        states=len(results),
        solved=values["solved"],
        mean_children=values["children"],
        mean_successful_children=values["successful children"],
        solved_per_1k_tokens=values["solved per 1k tokens"],
        children_per_1k_tokens=values["children per 1k tokens"],
        successful_children_per_1k_tokens=values["successful children per 1k tokens"],
        samples=sum(result.samples for result in results),
        cut_off_samples=sum(result.cut_off_samples for result in results),
        sample_success_rate=rate(
            sum(result.successes for result in results), sum(result.denominator for result in results)
        ),
        first_round_sample_success_rate=rate(
            sum(result.first_round_successes for result in results), first_round_denominator
        ),
        valid_rate=rate(sum(result.valid for result in results), sum(result.denominator for result in results)),
        feedback_fired=sum(result.feedback_fired for result in results),
        repaired_samples=sum(result.repaired_samples for result in results),
        repaired_successes=sum(result.repaired_successes for result in results),
        outcomes=sum((result.outcomes for result in results), SampleOutcomes()),
        errors=sum((result.errors for result in results), ErrorCounts()),
        mean_prompt_tokens=mean([result.prompt_tokens for result in results]),
        mean_generated_tokens=mean([result.generated_tokens for result in results]),
        mean_lean_seconds=mean([result.lean_seconds for result in results]),
        mean_sweep_lean_seconds=mean([result.sweep_lean_seconds for result in results]),
        mean_wall_seconds=mean([result.wall_seconds for result in results]),
        p90_wall_seconds=quantile([result.wall_seconds for result in results], 0.9),
    )


@dataclass(frozen=True)
class PairedMetric:
    """A metric of a variant against a reference on the states both searched, the bootstrap resampling those states."""

    variant: str
    reference: str
    metric: str
    states: int
    value: float
    reference_value: float
    difference: float
    interval_low: float
    interval_high: float
    # Two-sided bootstrap p-value, and after Holm's correction over the family (None outside it: the A/A pair).
    p_value: float
    holm_p_value: float | None = None
    significant: bool = False


def ratio_of_sums(values: np.ndarray, tokens: np.ndarray) -> np.ndarray:
    """Per bootstrap draw (row), the values' sum over the tokens' sum; 0 where no tokens, as `rate`."""
    totals = tokens.sum(axis=1)
    return np.divide(values.sum(axis=1), totals, out=np.zeros_like(totals), where=totals > 0)


def paired_metrics(
    variant: str,
    reference: str,
    variant_results: Sequence[StateResult],
    reference_results: Sequence[StateResult],
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> list[PairedMetric]:
    by_name = {result.name: result for result in reference_results}
    pairs = [(result, by_name[result.name]) for result in variant_results if result.name in by_name]
    ours = [pair[0] for pair in pairs]
    theirs = [pair[1] for pair in pairs]
    draws = np.random.default_rng(seed).integers(0, max(1, len(pairs)), size=(bootstrap_samples, len(pairs)))
    tail = (1 - confidence) / 2
    paired = []
    for metric in PRIMARY_METRICS:
        mine = np.array([metric.value(result) for result in ours], dtype=float)
        other = np.array([metric.value(result) for result in theirs], dtype=float)
        if metric.per_token:
            mine_tokens = np.array([result.generated_tokens for result in ours], dtype=float)
            other_tokens = np.array([result.generated_tokens for result in theirs], dtype=float)
            resampled = TOKENS_PER_UNIT * (
                ratio_of_sums(mine[draws], mine_tokens[draws]) - ratio_of_sums(other[draws], other_tokens[draws])
            )
        else:
            resampled = mine[draws].mean(axis=1) - other[draws].mean(axis=1) if pairs else np.zeros(bootstrap_samples)
        value, reference_value = metric_value(metric, ours), metric_value(metric, theirs)
        at_most = int((resampled <= 0).sum())
        at_least = int((resampled >= 0).sum())
        p_value = min(1.0, 2 * (min(at_most, at_least) + 1) / (bootstrap_samples + 1))
        paired.append(
            PairedMetric(
                variant=variant,
                reference=reference,
                metric=metric.name,
                states=len(pairs),
                value=value,
                reference_value=reference_value,
                difference=value - reference_value,
                interval_low=float(np.quantile(resampled, tail)),
                interval_high=float(np.quantile(resampled, 1 - tail)),
                p_value=p_value,
            )
        )
    return paired


def holm_corrected(metrics: Sequence[PairedMetric], level: float) -> list[PairedMetric]:
    """Holm's step-down correction over the family `metrics`, significant at family-wise `level`."""
    order = sorted(range(len(metrics)), key=lambda index: metrics[index].p_value)
    adjusted = [0.0] * len(metrics)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(metrics) - rank) * metrics[index].p_value))
        adjusted[index] = running
    return [
        dataclasses.replace(metric, holm_p_value=adjusted[index], significant=adjusted[index] <= level)
        for index, metric in enumerate(metrics)
    ]


@dataclass(frozen=True)
class FeedbackStratum:
    """States of a feedback variant by their first round's new states: what the round added within the same run."""

    first_round_children: str
    states: int
    fired: int
    # No successful first-round sample, a successful feedback sample.
    rescued: int
    added_children: int
    added_successful_children: int
    feedback_generated_tokens: int
    added_successful_children_per_1k_tokens: float


@dataclass(frozen=True)
class FeedbackReport:
    variant: str
    states: int
    fired: int
    first_round_solved: int
    solved: int
    first_round_children: int
    children: int
    first_round_successful_children: int
    successful_children: int
    first_round_generated_tokens: int
    feedback_generated_tokens: int
    # The first round's yield per 1k of its tokens, to set beside the round's in the strata.
    first_round_successful_children_per_1k_tokens: float
    strata: tuple[FeedbackStratum, ...]


def stratum_name(children: int) -> str:
    return f"{FEEDBACK_STRATA}+" if children >= FEEDBACK_STRATA else str(children)


def feedback_report(variant: str, results: Sequence[StateResult]) -> FeedbackReport:
    strata = []
    for stratum in range(FEEDBACK_STRATA + 1):
        chosen = [result for result in results if min(result.first_round_children, FEEDBACK_STRATA) == stratum]
        added = sum(result.successful_children - result.first_round_successful_children for result in chosen)
        tokens = sum(result.feedback_generated_tokens for result in chosen)
        strata.append(
            FeedbackStratum(
                first_round_children=stratum_name(stratum),
                states=len(chosen),
                fired=sum(result.feedback_fired for result in chosen),
                rescued=sum(result.solved and not result.first_round_solved for result in chosen),
                added_children=sum(result.children - result.first_round_children for result in chosen),
                added_successful_children=added,
                feedback_generated_tokens=tokens,
                added_successful_children_per_1k_tokens=TOKENS_PER_UNIT * rate(added, tokens),
            )
        )
    first_tokens = sum(result.first_round_generated_tokens for result in results)
    first_successful = sum(result.first_round_successful_children for result in results)
    return FeedbackReport(
        variant=variant,
        states=len(results),
        fired=sum(result.feedback_fired for result in results),
        first_round_solved=sum(result.first_round_solved for result in results),
        solved=sum(result.solved for result in results),
        first_round_children=sum(result.first_round_children for result in results),
        children=sum(result.children for result in results),
        first_round_successful_children=first_successful,
        successful_children=sum(result.successful_children for result in results),
        first_round_generated_tokens=first_tokens,
        feedback_generated_tokens=sum(result.feedback_generated_tokens for result in results),
        first_round_successful_children_per_1k_tokens=TOKENS_PER_UNIT * rate(first_successful, first_tokens),
        strata=tuple(strata),
    )


@dataclass(frozen=True)
class VariantResults:
    variant: str
    run_config: RunConfig
    results: tuple[StateResult, ...]


@dataclass(frozen=True)
class VariantComparison:
    summaries: tuple[VariantSummary, ...]
    # Every pairing with the baseline and the variants' own controls, Holm-corrected together.
    paired: tuple[PairedMetric, ...]
    # The second baseline against the first: the noise floor, outside the family.
    noise_floor: tuple[PairedMetric, ...]
    feedback: tuple[FeedbackReport, ...]
    family_size: int
    family_level: float


def pairings(variants: Sequence[str], config: SearchVariantsConfig) -> list[tuple[str, str]]:
    """(variant, reference) pairs of the family: each variant with the baseline and its own controls present."""
    present = set(variants)
    pairs = []
    for name in variants:
        if name in (config.baseline, config.second_baseline):
            continue
        known = [variant for variant in config.variants if variant.name == name]
        controls = known[0].compared_with if known else ()
        for reference in (config.baseline, *controls):
            if reference in present and (name, reference) not in pairs:
                pairs.append((name, reference))
    return pairs


def compare_variants(runs: Sequence[VariantResults], config: SearchVariantsConfig) -> VariantComparison:
    by_name = {run.variant: run for run in runs}

    def paired(name: str, reference: str) -> list[PairedMetric]:
        return paired_metrics(
            name,
            reference,
            by_name[name].results,
            by_name[reference].results,
            config.bootstrap_samples,
            config.confidence,
            config.seed,
        )

    family = [metric for name, reference in pairings(list(by_name), config) for metric in paired(name, reference)]
    level = 1 - config.confidence
    noise_floor = (
        paired(config.second_baseline, config.baseline)
        if config.second_baseline in by_name and config.baseline in by_name
        else []
    )
    return VariantComparison(
        summaries=tuple(variant_summary(run.variant, run.run_config.policy.temperature, run.results) for run in runs),
        paired=tuple(holm_corrected(family, level)),
        noise_floor=tuple(noise_floor),
        feedback=tuple(
            feedback_report(run.variant, run.results) for run in runs if run.run_config.policy.feedback.enabled
        ),
        family_size=len(family),
        family_level=level,
    )


def markdown(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def summary_table(summaries: Sequence[VariantSummary]) -> str:
    columns = [
        "variant",
        "states",
        "solved",
        "children",
        "successful children",
        "solved / 1k tok",
        "children / 1k tok",
        "successful children / 1k tok",
        "sample success (first round)",
        "valid",
        "cut off samples",
        "feedback fired",
        "repaired (successes)",
        "tokens / state",
        "Lean s / state (sweep)",
        "wall s / state (p90)",
    ]
    rows = [
        [
            summary.variant,
            str(summary.states),
            f"{summary.solved:.3f}",
            f"{summary.mean_children:.2f}",
            f"{summary.mean_successful_children:.2f}",
            f"{summary.solved_per_1k_tokens:.3f}",
            f"{summary.children_per_1k_tokens:.3f}",
            f"{summary.successful_children_per_1k_tokens:.3f}",
            f"{summary.sample_success_rate:.3f} ({summary.first_round_sample_success_rate:.3f})",
            f"{summary.valid_rate:.3f}",
            str(summary.cut_off_samples),
            str(summary.feedback_fired),
            f"{summary.repaired_samples} ({summary.repaired_successes})",
            f"{summary.mean_generated_tokens:.0f}",
            f"{summary.mean_lean_seconds:.1f} ({summary.mean_sweep_lean_seconds:.1f})",
            f"{summary.mean_wall_seconds:.1f} ({summary.p90_wall_seconds:.1f})",
        ]
        for summary in summaries
    ]
    return markdown(columns, rows)


def paired_table(metrics: Sequence[PairedMetric]) -> str:
    columns = ["variant", "against", "metric", "states", "variant value", "reference value", "Δ (CI)", "p", "Holm p"]
    rows = [
        [
            metric.variant,
            metric.reference,
            metric.metric,
            str(metric.states),
            f"{metric.value:.3f}",
            f"{metric.reference_value:.3f}",
            f"{metric.difference:+.3f} ({metric.interval_low:+.3f}, {metric.interval_high:+.3f})",
            f"{metric.p_value:.3f}",
            "-" if metric.holm_p_value is None else f"{metric.holm_p_value:.3f}{' *' if metric.significant else ''}",
        ]
        for metric in metrics
    ]
    return markdown(columns, rows)


def feedback_table(report: FeedbackReport) -> str:
    parts = [
        f"{report.variant}: the round fired at {report.fired} of {report.states} states",
        f"solved {report.first_round_solved} after the first round, {report.solved} in total",
        f"new states {report.first_round_children} -> {report.children}",
        f"successful ones {report.first_round_successful_children} -> {report.successful_children}",
        f"generated tokens {report.first_round_generated_tokens} first round, {report.feedback_generated_tokens} "
        f"feedback ({report.first_round_successful_children_per_1k_tokens:.3f} successful states per 1k first-round "
        "tokens)",
    ]
    head = "; ".join(parts) + ".\n\n"
    columns = [
        "first-round new states",
        "states",
        "fired",
        "rescued",
        "added states",
        "added successful states",
        "feedback tokens",
        "added successful / 1k feedback tokens",
    ]
    rows = [
        [
            stratum.first_round_children,
            str(stratum.states),
            str(stratum.fired),
            str(stratum.rescued),
            str(stratum.added_children),
            str(stratum.added_successful_children),
            str(stratum.feedback_generated_tokens),
            f"{stratum.added_successful_children_per_1k_tokens:.3f}",
        ]
        for stratum in report.strata
    ]
    return head + markdown(columns, rows)


def error_table(summaries: Sequence[VariantSummary]) -> str:
    """Per variant, its samples' outcomes and Lean errors as shares of its recorded samples."""
    outcome_names = [item.name for item in dataclasses.fields(SampleOutcomes)]
    error_names = [item.name for item in dataclasses.fields(ErrorCounts)]
    rows = []
    for summary in summaries:
        counts = [*dataclasses.astuple(summary.outcomes), *dataclasses.astuple(summary.errors)]
        rows.append([summary.variant, *(f"{rate(count, summary.samples):.3f}" for count in counts)])
    return markdown(["variant", *outcome_names, *error_names], rows)


def comparison_text(comparison: VariantComparison) -> str:
    level = comparison.family_level
    sections = [
        "## Variants\n\nPrimary: per state (solved: at least one successful sample; children: distinct new states the "
        "policy's samples reached; successful children: distinct ones on the reference proof), and the same per 1k "
        "generated tokens. Pooled sample success is secondary; samples cut off by the state's time cap count as "
        "failures.\n\n" + summary_table(comparison.summaries),
        f"## Paired comparisons\n\nPer state on the states both searched; 95% percentile bootstrap intervals over "
        f"states (not adjusted); two-sided bootstrap p-values, Holm-corrected over the family of "
        f"{comparison.family_size} tests (every pairing below × the six primary metrics; the A/A pair is not in it); "
        f"* marks a family-wise significant difference at {level:.2f}.\n\n" + paired_table(comparison.paired),
    ]
    if comparison.noise_floor:
        sections.append(
            "## Noise floor: the second baseline against the first\n\n" + paired_table(comparison.noise_floor)
        )
    for report in comparison.feedback:
        sections.append("## Feedback round, within the run\n\n" + feedback_table(report))
    sections.append("## Shares of each variant's samples\n\n" + error_table(comparison.summaries))
    return "\n".join(sections)
