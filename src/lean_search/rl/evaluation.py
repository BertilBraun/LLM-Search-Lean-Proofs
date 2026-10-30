"""Fixed-target evaluations: a problem set searched at a fixed budget with the served version, resumable.

A run directory holds config.toml (the search's run config, which the value benchmark reads for provenance),
results.jsonl (one SearchResult per problem), trees/<problem>.json.gz, progress.json (the problems without a result and,
for the held-out states, whether every state was sampled; the loop reads it) and, once complete, summary.json; a
repeated run of the same version holds comparison.json against the first, a probe slot's value arm comparison.json
against the slot's run with the reference value model.
"""

import asyncio
import contextlib
import dataclasses
import datetime
import json
import math
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.data import Problem
from lean_search.expert_iteration.pool_search import PRELOADED_HEADER_SHARE, common_headers
from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.monitoring.families import BandOutcome, FixedTargets, PairedDifference, ValueArmResult
from lean_search.rl.loop_config import ValueArmConfig
from lean_search.rl.renaming import StatementRenamings, search_problem
from lean_search.rl.search_models import open_search_models, run_config_text
from lean_search.search import CompletedSearch, RunConfig, SearchResult, StopReason, read_results, tree_record
from lean_search.search.config import parse_run_config
from lean_search.search.records import from_json_object, to_json, write_tree


class EvaluationKind(StrEnum):
    PROBE = "probe"
    MINIF2F = "minif2f"
    HELD_OUT_STATES = "held_out_states"


@dataclass(frozen=True)
class EvaluationRun:
    kind: EvaluationKind
    # A probe slot: the part slot % probe_parts of the probe set; None: the whole set, or another target.
    slot: int | None = None
    # > 0: another independent run of the same version and part (the run-to-run noise).
    repeat: int = 0
    # The slot's part searched again with the published value model, paired with the slot's run.
    value_arm: bool = False
    # REPLs of the run in place of the target's (0): version 0's baseline runs share the concurrency.
    concurrency: int = 0


@dataclass(frozen=True)
class EvaluationProblem:
    problem: Problem
    # The probe's difficulty stratum; empty for miniF2F.
    stratum: str = ""


@dataclass(frozen=True)
class StratumOutcome:
    stratum: str
    problems: int
    solved: int


@dataclass(frozen=True)
class EvaluationSummary:
    kind: EvaluationKind
    run_name: str
    policy_version: int
    value_version: int
    # For held-out states: states and policy samples, `solved` the successful samples.
    problems: int
    solved: int
    by_stratum: tuple[StratumOutcome, ...]
    expansion_budget: int
    expansions: int
    generated_tokens: int
    lean_seconds: float
    wall_seconds: float
    started_at: str
    finished_at: str
    samples: int = 0
    # Held-out states: the samples whose block runs completely in Lean (valid Lean, whatever state it reaches).
    valid_samples: int = 0
    # Searches stopped by the per-problem wall-clock cap rather than the expansion budget.
    wall_clock_stops: int = 0
    # A probe slot and its part of the probe set.
    slot: int | None = None
    part: int | None = None
    # A value arm: the paired comparison with the slot's run.
    value_arm: ValueArmResult | None = None

    @property
    def solve_rate(self) -> float:
        return self.solved / self.problems if self.problems else 0.0


@dataclass(frozen=True)
class RepeatComparison:
    """Two runs of one version on the same problems: the run-to-run noise."""

    problems: int
    first_solved: int
    second_solved: int
    # Solved by one run only; the difference's paired spread.
    only_first: int
    only_second: int

    @property
    def difference(self) -> int:
        return self.second_solved - self.first_solved

    @property
    def discordant(self) -> int:
        return self.only_first + self.only_second


@dataclass(frozen=True)
class SearchProgress:
    """A running evaluation's problems without a result, read by the loop to fill the GPUs beside it."""

    unfinished: int
    concurrency: int
    # Every problem had its last policy batch, so only Lean checks remain (the held-out states report it).
    generation_finished: bool = False
    # The held-out states finished so far: their samples, and those whose block ran completely in Lean.
    samples: int = 0
    valid_samples: int = 0

    @property
    def searches_in_flight(self) -> int:
        return min(self.unfinished, self.concurrency)

    @property
    def valid_rate(self) -> float | None:
        return self.valid_samples / self.samples if self.samples else None


@dataclass(frozen=True)
class EvaluationPaths:
    directory: Path

    @property
    def config(self) -> Path:
        return self.directory / "config.toml"

    @property
    def results(self) -> Path:
        return self.directory / "results.jsonl"

    @property
    def trees(self) -> Path:
        return self.directory / "trees"

    @property
    def summary(self) -> Path:
        return self.directory / "summary.json"

    @property
    def comparison(self) -> Path:
        return self.directory / "comparison.json"

    @property
    def progress(self) -> Path:
        return self.directory / "progress.json"


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def stratum_outcomes(problems: Sequence[EvaluationProblem], results: Sequence[SearchResult]) -> list[StratumOutcome]:
    solved = {result.problem_name for result in results if result.proved}
    strata = sorted({problem.stratum for problem in problems if problem.stratum})
    return [
        StratumOutcome(
            stratum,
            sum(problem.stratum == stratum for problem in problems),
            sum(problem.stratum == stratum and problem.problem.name in solved for problem in problems),
        )
        for stratum in strata
    ]


def search_summary(
    kind: EvaluationKind,
    run_name: str,
    versions: tuple[int, int],
    problems: Sequence[EvaluationProblem],
    results: Sequence[SearchResult],
    config: RunConfig,
    started_at: str,
    wall_seconds: float,
) -> EvaluationSummary:
    return EvaluationSummary(
        kind=kind,
        run_name=run_name,
        policy_version=versions[0],
        value_version=versions[1],
        problems=len(problems),
        solved=sum(result.proved for result in results),
        by_stratum=tuple(stratum_outcomes(problems, results)),
        expansion_budget=config.search.max_expansions,
        expansions=sum(result.accounting.expansions for result in results),
        generated_tokens=sum(result.accounting.generated_tokens for result in results),
        lean_seconds=sum(result.accounting.lean_seconds for result in results),
        wall_seconds=wall_seconds,
        started_at=started_at,
        finished_at=now(),
        wall_clock_stops=sum(result.stop_reason == StopReason.WALL_CLOCK_BUDGET for result in results),
    )


def compare_repeats(first: Sequence[SearchResult], second: Sequence[SearchResult]) -> RepeatComparison:
    first_solved = {result.problem_name for result in first if result.proved}
    second_solved = {result.problem_name for result in second if result.proved}
    assert {result.problem_name for result in first} == {result.problem_name for result in second}
    return RepeatComparison(
        problems=len(first),
        first_solved=len(first_solved),
        second_solved=len(second_solved),
        only_first=len(first_solved - second_solved),
        only_second=len(second_solved - first_solved),
    )


@dataclass(frozen=True)
class RollingProbe:
    """The last slots together, each part of the probe set once."""

    slots: tuple[int, ...]
    problems: int
    solved: int
    by_stratum: tuple[StratumOutcome, ...]


def rolling_probe(summaries: Sequence[EvaluationSummary]) -> RollingProbe:
    strata: dict[str, tuple[int, int]] = {}
    for summary in summaries:
        for outcome in summary.by_stratum:
            problems, solved = strata.get(outcome.stratum, (0, 0))
            strata[outcome.stratum] = (problems + outcome.problems, solved + outcome.solved)
    return RollingProbe(
        slots=tuple(summary.slot for summary in summaries if summary.slot is not None),
        problems=sum(summary.problems for summary in summaries),
        solved=sum(summary.solved for summary in summaries),
        by_stratum=tuple(StratumOutcome(stratum, problems, solved) for stratum, (problems, solved) in strata.items()),
    )


@dataclass(frozen=True)
class BaselineDifferences:
    """A probe slot's solve rate minus the mean of version 0's runs of the same part (the same problems), so the
    parts' difficulty cancels; and the mean of that over the last slots, each part once (None until they all have
    one)."""

    this_slot: float | None
    last_slots: float | None


def baseline_difference(summary: EvaluationSummary, baseline: Sequence[EvaluationSummary]) -> float | None:
    if not baseline:
        return None
    return summary.solve_rate - statistics.fmean(run.solve_rate for run in baseline)


def mean_or_none(values: Sequence[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return statistics.fmean(known) if values and len(known) == len(values) else None


def binomial_upper_tail(successes: int, trials: int) -> float:
    """P(X >= successes) for X ~ Binomial(trials, 1/2)."""
    return sum(math.comb(trials, count) for count in range(successes, trials + 1)) / 2**trials


def binomial_cumulative(successes: int, trials: int, probability: float) -> float:
    """P(X <= successes) for X ~ Binomial(trials, probability), 0 < probability < 1."""
    log_success, log_failure = math.log(probability), math.log1p(-probability)
    total = sum(
        math.exp(
            math.lgamma(trials + 1)
            - math.lgamma(count + 1)
            - math.lgamma(trials - count + 1)
            + count * log_success
            + (trials - count) * log_failure
        )
        for count in range(successes + 1)
    )
    return min(1.0, total)


def bisected(decreasing: Callable[[float], float], target: float) -> float:
    """The probability in (0, 1) where a function decreasing in it crosses the target."""
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if decreasing(middle) > target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def clopper_pearson(successes: int, trials: int, confidence: float) -> tuple[float, float]:
    """The exact interval of a binomial probability; [0, 1] without trials."""
    tail = (1 - confidence) / 2
    lower = 0.0
    if successes > 0:
        lower = 1 - bisected(lambda share: binomial_cumulative(trials - successes, trials, share), tail)
    upper = 1.0
    if successes < trials:
        upper = bisected(lambda share: binomial_cumulative(successes, trials, share), tail)
    return lower, upper


def paired_difference(
    runs: int, problems: int, only_reference: int, only_published: int, confidence: float
) -> PairedDifference:
    """The paired solve-rate difference with McNemar's exact interval: given the d problems one arm solved, the
    published arm's share of them is binomial, and the difference is (2 · share − 1) · d / problems."""
    discordant = only_reference + only_published
    lower_share, upper_share = clopper_pearson(only_published, discordant, confidence)
    known = problems > 0
    return PairedDifference(
        runs=runs,
        problems=problems,
        only_reference=only_reference,
        only_published=only_published,
        difference=(only_published - only_reference) / problems if known else None,
        lower=(2 * lower_share - 1) * discordant / problems if known else None,
        upper=(2 * upper_share - 1) * discordant / problems if known else None,
        worse_p_value=binomial_upper_tail(only_reference, discordant),
        better_p_value=binomial_upper_tail(only_published, discordant),
    )


def pooled_difference(
    this_slot: PairedDifference, earlier: Sequence[ValueArmResult], confidence: float
) -> PairedDifference:
    return paired_difference(
        this_slot.runs + len(earlier),
        this_slot.problems + sum(result.this_slot.problems for result in earlier),
        this_slot.only_reference + sum(result.this_slot.only_reference for result in earlier),
        this_slot.only_published + sum(result.this_slot.only_published for result in earlier),
        confidence,
    )


def value_arm_result(
    reference: Sequence[SearchResult],
    published: Sequence[SearchResult],
    slot: int,
    part: int,
    value_versions: tuple[int, int],
    earlier: Sequence[ValueArmResult],
    config: ValueArmConfig,
) -> ValueArmResult:
    """Paired per problem with the slot's run with the reference value model; pooled with the `earlier` value arms of
    the same published value model and of every one."""
    comparison = compare_repeats(reference, published)
    this_slot = paired_difference(
        1, comparison.problems, comparison.only_first, comparison.only_second, config.confidence
    )
    same_version = [result for result in earlier if result.published_value_version == value_versions[1]]
    same_value_version = pooled_difference(this_slot, same_version, config.confidence)
    return ValueArmResult(
        slot=slot,
        part=part,
        reference_value_version=value_versions[0],
        published_value_version=value_versions[1],
        reference_solved=comparison.first_solved,
        published_solved=comparison.second_solved,
        this_slot=this_slot,
        same_value_version=same_value_version,
        all_value_versions=pooled_difference(this_slot, earlier, config.confidence),
        worse=same_value_version.worse_p_value < config.significance,
    )


def difference_text(name: str, difference: PairedDifference) -> str:
    if difference.difference is None or difference.lower is None or difference.upper is None:
        return f"{name}: no problems"
    return (
        f"{name} {difference.difference:+.3f} [{difference.lower:+.3f}, {difference.upper:+.3f}] over "
        f"{difference.problems} problems in {difference.runs} runs ({difference.only_published} solved by the "
        f"published model only, {difference.only_reference} by v0 only; p(worse) = {difference.worse_p_value:.3f})"
    )


def value_arm_text(result: ValueArmResult) -> str:
    return (
        f"Value arm of probe slot {result.slot} (part {result.part}): value v{result.published_value_version} "
        f"{result.published_solved}, v{result.reference_value_version} {result.reference_solved}; "
        + "; ".join(
            (
                difference_text("this slot", result.this_slot),
                difference_text("pooled over this value model", result.same_value_version),
                difference_text("pooled over every value model", result.all_value_versions),
            )
        )
        + ("; worse than v0" if result.worse else "")
    )


def band_outcomes(outcomes: Sequence[StratumOutcome]) -> dict[str, BandOutcome]:
    return {outcome.stratum: BandOutcome(outcome.problems, outcome.solved) for outcome in outcomes}


def repeats_to_compare(first: EvaluationPaths, finished: EvaluationPaths, repeat: int) -> list[EvaluationPaths]:
    """The repeats to compare with the first run now that `finished` (repeat `repeat`) is complete: a repeat itself once
    the first run is; the first run every complete repeat not yet compared (the loop runs version 0's runs at once)."""
    if repeat:
        return [finished] if first.summary.exists() else []
    repeats = sorted(first.directory.parent.glob(f"{first.directory.name}_repeat*"))
    return [
        EvaluationPaths(directory)
        for directory in repeats
        if (directory / "summary.json").exists() and not (directory / "comparison.json").exists()
    ]


def fixed_targets_record(
    summary: EvaluationSummary,
    comparison: RepeatComparison | None = None,
    rolling: RollingProbe | None = None,
    baseline: BaselineDifferences | None = None,
) -> FixedTargets:
    """`comparison`: a repeated run against the first; `rolling`: a probe slot's last slots, each part once;
    `baseline`: a probe slot against version 0's runs of its part."""
    match summary.kind:
        case EvaluationKind.PROBE if comparison is not None:
            return FixedTargets(
                probe_part=summary.part,
                probe_problems=summary.problems,
                probe_expansion_budget=summary.expansion_budget,
                evaluation_seconds=summary.wall_seconds,
                probe_wall_clock_stops=summary.wall_clock_stops,
                probe_repeat_solved=summary.solved,
                probe_repeat_difference=comparison.difference,
                probe_repeat_discordant=comparison.discordant,
            )
        case EvaluationKind.PROBE:
            return FixedTargets(
                probe_solved=summary.solved,
                probe_problems=summary.problems,
                probe_expansion_budget=summary.expansion_budget,
                probe_by_difficulty=band_outcomes(summary.by_stratum),
                evaluation_seconds=summary.wall_seconds,
                probe_wall_clock_stops=summary.wall_clock_stops,
                probe_slot=summary.slot,
                probe_part=summary.part,
                probe_rolling_solved=None if rolling is None else rolling.solved,
                probe_rolling_problems=None if rolling is None else rolling.problems,
                probe_rolling_by_difficulty={} if rolling is None else band_outcomes(rolling.by_stratum),
                probe_baseline_difference=None if baseline is None else baseline.this_slot,
                probe_rolling_baseline_difference=None if baseline is None else baseline.last_slots,
            )
        case EvaluationKind.MINIF2F:
            return FixedTargets(
                minif2f_valid_solved=summary.solved,
                minif2f_valid_problems=summary.problems,
                expansion_budget=summary.expansion_budget,
                evaluation_seconds=summary.wall_seconds,
                minif2f_wall_clock_stops=summary.wall_clock_stops,
            )
        case EvaluationKind.HELD_OUT_STATES:
            return FixedTargets(
                held_out_success=summary.solved / summary.samples if summary.samples else None,
                held_out_states=summary.problems,
                held_out_valid_rate=summary.valid_samples / summary.samples if summary.samples else None,
                evaluation_seconds=summary.wall_seconds,
            )


def keep_config(paths: EvaluationPaths, config: RunConfig) -> None:
    """Compared parsed, defaults filled in: a run resumed by newer code that writes fields the older left out (at
    their defaults) keeps its config."""
    text = run_config_text(config)
    if paths.config.exists() and parse_run_config(paths.config.read_text(encoding="utf-8")) != parse_run_config(text):
        raise ValueError(f"{paths.config} holds another config; an evaluation run keeps one.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(text, encoding="utf-8")


async def search_problem_set(
    problems: Sequence[EvaluationProblem],
    config: RunConfig,
    paths: EvaluationPaths,
    log: Callable[[str], None],
    renamings: StatementRenamings | None = None,
) -> list[SearchResult]:
    """Searches the problems without a result yet (renamed when given renamings); returns every problem's result."""
    keep_config(paths, config)
    done = read_results(paths.results) if paths.results.exists() else []
    finished = {result.problem_name for result in done}
    pending = [problem.problem for problem in problems if problem.problem.name not in finished]
    results = list(done)
    write_json_atomically(paths.progress, SearchProgress(len(pending), config.lean.concurrency))

    async def on_completed(completed: CompletedSearch) -> None:
        result = completed.result
        if completed.tree is not None:
            record = tree_record(completed.tree, completed.tree.root.state.statement, result)
            await asyncio.to_thread(write_tree, paths.trees / f"{result.problem_name}.json.gz", record)
        with paths.results.open("a", encoding="utf-8") as handle:
            handle.write(to_json(result) + "\n")
        results.append(result)
        write_json_atomically(paths.progress, SearchProgress(len(problems) - len(results), config.lean.concurrency))
        solved = sum(result.proved for result in results)
        log(f"[{len(results)}/{len(problems)}] {result.problem_name}: {result.stop_reason} | solved {solved}")

    if pending:
        async with contextlib.AsyncExitStack() as stack:
            models = await stack.enter_async_context(open_search_models(config))
            pool = await stack.enter_async_context(
                LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction)
            )
            await pool.start(common_headers(pending, PRELOADED_HEADER_SHARE))
            semaphore = asyncio.Semaphore(config.lean.concurrency)
            not_started = len(pending)
            searching = 0

            async def search_one(problem: Problem) -> None:
                nonlocal not_started, searching
                async with semaphore:
                    not_started -= 1
                    searching += 1
                    async with pool.acquire() as repl:
                        completed = await search_problem(
                            problem, repl, models.expander, models.priority_function, config.search, renamings
                        )
                    searching -= 1
                    # In the tail the loop's sampling takes the freed searches, so the freed REPLs go.
                    if not not_started:
                        await pool.stop_idle_processes(searching)
                    await on_completed(completed)

            await asyncio.gather(*(search_one(problem) for problem in pending))
        if renamings is not None:
            log(
                f"Renaming: {renamings.missing} problems without a renaming, "
                f"{renamings.failed_original_checks} proofs failed the check against the original statement"
            )
    return results


async def run_problem_set_evaluation(
    kind: EvaluationKind,
    run_name: str,
    versions: tuple[int, int],
    problems: Sequence[EvaluationProblem],
    config: RunConfig,
    paths: EvaluationPaths,
    log: Callable[[str], None],
    renamings: StatementRenamings | None = None,
    slot: int | None = None,
    part: int | None = None,
) -> EvaluationSummary:
    """`slot` and `part`: the probe slot and the part of the probe set the problems are."""
    started_at = now()
    started = time.monotonic()
    results = await search_problem_set(problems, config, paths, log, renamings)
    summary = search_summary(
        kind, run_name, versions, problems, results, config, started_at, time.monotonic() - started
    )
    summary = dataclasses.replace(summary, slot=slot, part=part)
    write_json_atomically(paths.summary, summary)
    return summary


def read_summary(path: Path) -> EvaluationSummary:
    return from_json_object(EvaluationSummary, json.loads(path.read_text(encoding="utf-8")))


def read_search_progress(path: Path) -> SearchProgress | None:
    """None before the job wrote it."""
    if not path.exists():
        return None
    return from_json_object(SearchProgress, json.loads(path.read_text(encoding="utf-8")))
