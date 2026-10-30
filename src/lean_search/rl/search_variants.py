"""Search variants on the held-out states (experiments/search_variants.py): per variant the per-sample success, valid
Lean, errors, children and costs, each paired with the baseline on the states both searched.

A variant changes the loop's search template (temperature, the feedback round, the failed automation in the prompt,
name repair) and runs the loop's held-out evaluation with it. Success counts every policy sample at the state, the
feedback round's and the repaired ones included, by the run that counted (`single_step.root_samples`); the first
round's rate compares sample for sample with the baseline, `repaired_successes` is what repair added.
"""

import dataclasses
import math
import random
import re
import tomllib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.policy.config import FeedbackConfig
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_models import evaluation_run_config, run_config_text
from lean_search.rl.single_step import StateProblem, root_samples, single_step_run_config
from lean_search.search import RunConfig, TreeRecord
from lean_search.search.config import parse_run_config
from lean_search.search.records import from_json_object
from lean_search.search.search import NameRepairConfig
from lean_search.search.tree import EdgeOutcome, Failure, FailureKind

VARIANT_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


@dataclass(frozen=True)
class SearchVariant:
    # The variant's directory name; the config's `baseline` names the variant the others are paired with.
    name: str
    # None keeps the template's.
    temperature: float | None = None
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    failed_automation_in_prompt: bool = False
    name_repair: NameRepairConfig = field(default_factory=NameRepairConfig)


@dataclass(frozen=True)
class SearchVariantsConfig:
    # Results under $LEAN_SEARCH_RUNS/<name>/v<served policy version>/<variant>/.
    name: str
    variants: tuple[SearchVariant, ...]
    baseline: str = "baseline"
    # The paired comparison's bootstrap over states.
    bootstrap_samples: int = 2000
    confidence: float = 0.95
    seed: int = 0

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
    if config.bootstrap_samples < 1 or not 0 < config.confidence < 1:
        raise ValueError("bootstrap_samples must be positive and confidence in (0, 1).")
    return config


def load_search_variants_config(path: Path) -> SearchVariantsConfig:
    return parse_search_variants_config(path.read_text(encoding="utf-8"))


def variant_run_config(template: RunConfig, variant: SearchVariant, target: EvaluationTarget) -> RunConfig:
    """The loop's held-out evaluation of the template with the variant's settings; validated like a config file."""
    policy = dataclasses.replace(
        template.policy,
        temperature=template.policy.temperature if variant.temperature is None else variant.temperature,
        feedback=variant.feedback,
        failed_automation_in_prompt=variant.failed_automation_in_prompt,
    )
    search = dataclasses.replace(template.search, name_repair=variant.name_repair)
    changed = dataclasses.replace(template, policy=policy, search=search)
    return parse_run_config(run_config_text(single_step_run_config(evaluation_run_config(changed, target))))


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


@dataclass(frozen=True)
class StateResult:
    name: str
    samples: int
    successes: int
    # Samples whose block ran completely.
    valid: int
    feedback_samples: int
    feedback_successes: int
    # Samples whose names the search repaired before the run that counts.
    repaired_samples: int
    repaired_successes: int
    # Distinct new states the policy's blocks reached.
    children: int
    outcomes: SampleOutcomes
    errors: ErrorCounts
    prompt_tokens: int
    generated_tokens: int
    lean_seconds: float
    wall_seconds: float

    @property
    def first_round_samples(self) -> int:
        return self.samples - self.feedback_samples

    @property
    def first_round_successes(self) -> int:
        return self.successes - self.feedback_successes


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


def state_result(name: str, record: TreeRecord, reference_keys: frozenset[tuple[str, ...]]) -> StateResult:
    samples = root_samples(record, reference_keys)
    outcomes: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    for sample in samples:
        outcome = sample_outcome(sample.edge.outcome, sample.executed.failure)
        outcomes[outcome.value] += sample.sample_count
        if outcome == SampleOutcome.LEAN_ERROR and sample.executed.failure is not None:
            errors[error_category(sample.executed.failure).value] += sample.sample_count
    feedback = [sample for sample in samples if sample.edge.feedback]
    repaired = [sample for sample in samples if sample.executed.repaired]
    accounting = record.result.accounting
    return StateResult(
        name=name,
        samples=sum(sample.sample_count for sample in samples),
        successes=sum(sample.sample_count for sample in samples if sample.success),
        valid=sum(sample.sample_count for sample in samples if sample.valid),
        feedback_samples=sum(sample.sample_count for sample in feedback),
        feedback_successes=sum(sample.sample_count for sample in feedback if sample.success),
        repaired_samples=sum(sample.sample_count for sample in repaired),
        repaired_successes=sum(sample.sample_count for sample in repaired if sample.success),
        children=sum(sample.edge.outcome == EdgeOutcome.CHILD for sample in samples),
        outcomes=SampleOutcomes(**outcomes),
        errors=ErrorCounts(**errors),
        prompt_tokens=accounting.prompt_tokens,
        generated_tokens=accounting.generated_tokens,
        lean_seconds=accounting.lean_seconds,
        wall_seconds=accounting.wall_seconds,
    )


def state_results(states: Sequence[StateProblem], records: Sequence[TreeRecord]) -> list[StateResult]:
    return [
        state_result(state.problem.name, record, state.reference_keys)
        for state, record in zip(states, records, strict=True)
    ]


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


@dataclass(frozen=True)
class VariantSummary:
    variant: str
    # The loop's published policy version the servers served.
    policy_version: int
    temperature: float
    states: int
    samples: int
    successes: int
    valid: int
    success_rate: float
    valid_rate: float
    # The first request's samples alone (the baseline's kind of sample).
    first_round_success_rate: float
    # States with at least one successful sample.
    states_with_success: int
    feedback_rounds: int
    feedback_samples: int
    feedback_success_rate: float
    repaired_samples: int
    repaired_successes: int
    mean_children: float
    # States whose blocks reached fewer than two new states.
    states_below_two_children: int
    outcomes: SampleOutcomes
    errors: ErrorCounts
    mean_prompt_tokens: float
    mean_generated_tokens: float
    mean_lean_seconds: float
    mean_wall_seconds: float
    p90_wall_seconds: float
    # This variant's invocations, summed (resumed runs search only the states without a tree).
    run_wall_seconds: float


def variant_summary(
    variant: str, policy_version: int, temperature: float, results: Sequence[StateResult], run_wall_seconds: float
) -> VariantSummary:
    samples = sum(result.samples for result in results)
    successes = sum(result.successes for result in results)
    valid = sum(result.valid for result in results)
    first_round_samples = sum(result.first_round_samples for result in results)
    feedback_samples = sum(result.feedback_samples for result in results)
    return VariantSummary(
        variant=variant,
        policy_version=policy_version,
        temperature=temperature,
        states=len(results),
        samples=samples,
        successes=successes,
        valid=valid,
        success_rate=rate(successes, samples),
        valid_rate=rate(valid, samples),
        first_round_success_rate=rate(sum(result.first_round_successes for result in results), first_round_samples),
        states_with_success=sum(result.successes > 0 for result in results),
        feedback_rounds=sum(result.feedback_samples > 0 for result in results),
        feedback_samples=feedback_samples,
        feedback_success_rate=rate(sum(result.feedback_successes for result in results), feedback_samples),
        repaired_samples=sum(result.repaired_samples for result in results),
        repaired_successes=sum(result.repaired_successes for result in results),
        mean_children=mean([result.children for result in results]),
        states_below_two_children=sum(result.children < 2 for result in results),
        outcomes=sum((result.outcomes for result in results), SampleOutcomes()),
        errors=sum((result.errors for result in results), ErrorCounts()),
        mean_prompt_tokens=mean([result.prompt_tokens for result in results]),
        mean_generated_tokens=mean([result.generated_tokens for result in results]),
        mean_lean_seconds=mean([result.lean_seconds for result in results]),
        mean_wall_seconds=mean([result.wall_seconds for result in results]),
        p90_wall_seconds=quantile([result.wall_seconds for result in results], 0.9),
        run_wall_seconds=run_wall_seconds,
    )


@dataclass(frozen=True)
class PairedComparison:
    """A variant against the baseline on the states both searched, the bootstrap resampling those states."""

    variant: str
    baseline: str
    states: int
    success_rate: float
    baseline_success_rate: float
    difference: float
    interval_low: float
    interval_high: float
    valid_rate_difference: float
    # States with a successful sample in one of the two runs only.
    states_only_variant: int
    states_only_baseline: int
    mean_children_difference: float
    generated_tokens_ratio: float
    wall_seconds_ratio: float


def pooled_rate(results: Sequence[StateResult]) -> float:
    return rate(sum(result.successes for result in results), sum(result.samples for result in results))


def paired_comparison(
    variant: str,
    baseline: str,
    variant_results: Sequence[StateResult],
    baseline_results: Sequence[StateResult],
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> PairedComparison:
    by_name = {result.name: result for result in baseline_results}
    pairs = [(result, by_name[result.name]) for result in variant_results if result.name in by_name]
    ours = [pair[0] for pair in pairs]
    theirs = [pair[1] for pair in pairs]
    generator = random.Random(seed)
    differences = []
    for _ in range(bootstrap_samples):
        drawn = [pairs[generator.randrange(len(pairs))] for _ in pairs] if pairs else []
        differences.append(pooled_rate([pair[0] for pair in drawn]) - pooled_rate([pair[1] for pair in drawn]))
    tail = (1 - confidence) / 2
    baseline_tokens = sum(result.generated_tokens for result in theirs)
    baseline_wall = sum(result.wall_seconds for result in theirs)
    return PairedComparison(
        variant=variant,
        baseline=baseline,
        states=len(pairs),
        success_rate=pooled_rate(ours),
        baseline_success_rate=pooled_rate(theirs),
        difference=pooled_rate(ours) - pooled_rate(theirs),
        interval_low=quantile(differences, tail),
        interval_high=quantile(differences, 1 - tail),
        valid_rate_difference=rate(sum(result.valid for result in ours), sum(result.samples for result in ours))
        - rate(sum(result.valid for result in theirs), sum(result.samples for result in theirs)),
        states_only_variant=sum(mine.successes > 0 and not other.successes for mine, other in pairs),
        states_only_baseline=sum(other.successes > 0 and not mine.successes for mine, other in pairs),
        mean_children_difference=mean([mine.children - other.children for mine, other in pairs]),
        generated_tokens_ratio=rate(sum(result.generated_tokens for result in ours), baseline_tokens),
        wall_seconds_ratio=sum(result.wall_seconds for result in ours) / baseline_wall if baseline_wall else 0.0,
    )


@dataclass(frozen=True)
class VariantComparison:
    summaries: tuple[VariantSummary, ...]
    paired: tuple[PairedComparison, ...]


def comparison_table(comparison: VariantComparison) -> str:
    """Markdown: one row per variant, its paired difference to the baseline beside its own numbers."""
    paired = {entry.variant: entry for entry in comparison.paired}
    columns = [
        "variant",
        "states",
        "samples",
        "success",
        "first round",
        "valid",
        "Δ success vs baseline (CI) on states",
        "only variant / only baseline",
        "children",
        "<2 children",
        "feedback rounds",
        "repaired (successes)",
        "tokens/state",
        "wall s/state (p90)",
    ]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for summary in comparison.summaries:
        entry = paired.get(summary.variant)
        difference = (
            f"{entry.difference:+.3f} ({entry.interval_low:+.3f}, {entry.interval_high:+.3f}) on {entry.states}"
            if entry
            else "-"
        )
        only = f"{entry.states_only_variant} / {entry.states_only_baseline}" if entry else "-"
        lines.append(
            f"| {summary.variant} | {summary.states} | {summary.samples} | {summary.success_rate:.3f} | "
            f"{summary.first_round_success_rate:.3f} | {summary.valid_rate:.3f} | {difference} | {only} | "
            f"{summary.mean_children:.2f} | {summary.states_below_two_children} | {summary.feedback_rounds} | "
            f"{summary.repaired_samples} ({summary.repaired_successes}) | {summary.mean_generated_tokens:.0f} | "
            f"{summary.mean_wall_seconds:.1f} ({summary.p90_wall_seconds:.1f}) |"
        )
    return "\n".join(lines) + "\n"


def error_table(summaries: Sequence[VariantSummary]) -> str:
    """Markdown: per variant, its samples' outcomes and Lean errors as shares of its samples."""
    outcome_names = [item.name for item in dataclasses.fields(SampleOutcomes)]
    error_names = [item.name for item in dataclasses.fields(ErrorCounts)]
    columns = [*outcome_names, *error_names]
    lines = ["| variant | " + " | ".join(columns) + " |", "|" + "---|" * (len(columns) + 1)]
    for summary in summaries:
        counts = [*dataclasses.astuple(summary.outcomes), *dataclasses.astuple(summary.errors)]
        shares = " | ".join(f"{rate(count, summary.samples):.3f}" for count in counts)
        lines.append(f"| {summary.variant} | {shares} |")
    return "\n".join(lines) + "\n"
