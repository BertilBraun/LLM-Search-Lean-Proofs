"""One rating per version from every finished probe run: logit P(version v proves problem p) = ability_v - difficulty_p.

Each probe slot searches a third of the probe set, so consecutive versions never share problems; the fit estimates each
problem's difficulty from every version that searched it, which puts all versions on one scale against version 0 (an
Elo-like curve on a fixed target). A pass pools the last run of every third into one ability, the whole set once; the
headline compares passes. The intervals resample problems. src/lean_search/rl/README.md, "Fixed targets".

Reads the run directory's files directly (no model code), so the recorder beside the dashboard stays small.
"""

import json
import sys
import time
import traceback
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lean_search.monitoring.families import PassComparison, PassRating, ProbeRatings, VersionRating
from lean_search.monitoring.store import MetricsWriter
from lean_search.search.records import read_results

# Weak priors, so that a version or problem solved every time (or never) keeps a finite estimate.
DIFFICULTY_PRIOR = 0.1
ABILITY_PRIOR = 0.01
MAX_NEWTON_STEPS = 500
CONVERGED_STEP = 1e-6
BOOTSTRAP_SAMPLES = 200


@dataclass(frozen=True)
class ProbeOutcome:
    problem: str
    proved: bool
    # The expansions its first proof took; None when unproved.
    expansions_to_proof: int | None


@dataclass(frozen=True)
class ProbeRun:
    name: str
    policy_version: int
    value_version: int
    # The third of the probe set it searched; None for a run of the whole set.
    part: int | None
    finished_at: str
    expansion_budget: int
    wall_clock_stops: int
    outcomes: tuple[ProbeOutcome, ...]


@dataclass(frozen=True)
class FinishedRuns:
    runs: tuple[ProbeRun, ...]
    # Finished runs whose summary or results could not be read.
    unreadable: int


@dataclass(frozen=True)
class LoopMarkers:
    rejected_versions: tuple[int, ...] = ()
    # The first version trained with the reward fix of 2026-10-31 (its first phase publishes it).
    reward_fix_version: int | None = None


def read_probe_run(directory: Path) -> ProbeRun:
    """summary.json (rl/evaluation.py's EvaluationSummary) and results.jsonl of a finished evaluation."""
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    return ProbeRun(
        name=directory.name,
        policy_version=summary["policy_version"],
        value_version=summary["value_version"],
        part=summary.get("part"),
        finished_at=summary["finished_at"],
        expansion_budget=summary["expansion_budget"],
        wall_clock_stops=summary.get("wall_clock_stops", 0),
        outcomes=tuple(
            ProbeOutcome(
                result.problem_name,
                result.proved,
                (result.solved_at or result.accounting).expansions if result.proved else None,
            )
            for result in read_results(directory / "results.jsonl")
        ),
    )


def finished_probe_runs(evaluations: Path) -> FinishedRuns:
    """The probe runs with a summary (a run still searching would rate on its easy problems only), in the order they
    finished; value arms left out, since they search the same version with another value model."""
    runs = []
    unreadable = 0
    for directory in sorted(evaluations.glob("probe_*")):
        if "_value_arm" in directory.name or not (directory / "summary.json").exists():
            continue
        try:
            run = read_probe_run(directory)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"{directory.name} is not rated: {error!r}", file=sys.stderr)
            unreadable += 1
            continue
        if run.outcomes:
            runs.append(run)
        else:
            unreadable += 1
    return FinishedRuns(tuple(sorted(runs, key=lambda run: run.finished_at)), unreadable)


def json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_markers(run_directory: Path) -> LoopMarkers:
    """`rejected_versions.jsonl` and `reward_fix.json` of the loop (rl/health_checks.py), and the version the fix's
    first phase published (`models/versions.jsonl`, trigger "phase <n>": rollbacks publish versions too). A marker that
    cannot be read counts as absent, as the loop treats it."""
    try:
        rejected = tuple(sorted({line["version"] for line in json_lines(run_directory / "rejected_versions.jsonl")}))
    except (OSError, ValueError, KeyError, TypeError):
        rejected = ()
    try:
        first_phase = json.loads((run_directory / "reward_fix.json").read_text(encoding="utf-8"))["first_phase"]
        published = json_lines(run_directory / "models" / "versions.jsonl")
        fix_version = next((line["version"] for line in published if line["trigger"] == f"phase {first_phase}"), None)
    except (OSError, ValueError, KeyError, TypeError):
        fix_version = None
    return LoopMarkers(rejected_versions=rejected, reward_fix_version=fix_version)


@dataclass(frozen=True)
class Fit:
    ability: np.ndarray
    difficulty: np.ndarray


def fit_abilities(
    groups: np.ndarray, problems: np.ndarray, proved: np.ndarray, weights: np.ndarray, group_count: int
) -> Fit:
    """Newton steps on both parameter blocks (each block's Hessian is diagonal) until they settle; group 0 stays the
    anchor at 0. The difficulty prior counts once per draw of its problem, so a bootstrap shrinks as the point fit."""
    problem_count = len(weights)
    ability = np.zeros(group_count)
    difficulty = np.zeros(problem_count)
    row_weights = weights[problems]
    difficulty_prior = DIFFICULTY_PRIOR * weights
    for _ in range(MAX_NEWTON_STEPS):
        probability = 1 / (1 + np.exp(difficulty[problems] - ability[groups]))
        residual = row_weights * (proved - probability)
        curvature = row_weights * probability * (1 - probability)
        ability_step = (np.bincount(groups, residual, group_count) - ABILITY_PRIOR * ability) / (
            np.bincount(groups, curvature, group_count) + ABILITY_PRIOR
        )
        ability_step[0] = 0.0
        gradient = -np.bincount(problems, residual, problem_count) - difficulty_prior * difficulty
        curvature_sum = np.bincount(problems, curvature, problem_count) + difficulty_prior
        difficulty_step = np.divide(gradient, curvature_sum, out=np.zeros(problem_count), where=curvature_sum > 0)
        ability += np.clip(ability_step, -1.0, 1.0)
        difficulty += np.clip(difficulty_step, -1.0, 1.0)
        if max(np.abs(ability_step).max(), np.abs(difficulty_step).max()) < CONVERGED_STEP:
            break
    return Fit(ability, difficulty)


def solved_within(outcomes: Sequence[ProbeOutcome], budget: int) -> float:
    return sum(
        outcome.proved and outcome.expansions_to_proof is not None and outcome.expansions_to_proof <= budget
        for outcome in outcomes
    ) / len(outcomes)


def rating_budgets(expansion_budget: int) -> tuple[int, ...]:
    """1, 2, 4, ... up to the probe's budget, which is always the last."""
    budgets = []
    budget = 1
    while budget < expansion_budget:
        budgets.append(budget)
        budget *= 2
    return (*budgets, expansion_budget)


def latest_pass(runs: Sequence[ProbeRun], parts: Sequence[int]) -> tuple[ProbeRun, ...] | None:
    """The last of the runs on each part; None unless there are parts and every one has a run."""
    latest = {run.part: run for run in runs if run.part is not None}
    return tuple(latest[part] for part in parts) if parts and all(part in latest for part in parts) else None


def names(runs: Sequence[ProbeRun]) -> set[str]:
    return {run.name for run in runs}


def projected_solved(ability: float, difficulty: np.ndarray) -> float:
    """Problems of the whole probe set a version of this ability is expected to prove."""
    return float(np.sum(1 / (1 + np.exp(difficulty - ability))))


class Rater:
    """The outcomes as arrays, fitted with any grouping of the runs into abilities (group 0: the anchor version)."""

    def __init__(self, runs: Sequence[ProbeRun], seed: int) -> None:
        self.problem_names = sorted({outcome.problem for run in runs for outcome in run.outcomes})
        problem_index = {problem: index for index, problem in enumerate(self.problem_names)}
        self.run_of_row = np.array([index for index, run in enumerate(runs) for _ in run.outcomes])
        self.problems = np.array([problem_index[outcome.problem] for run in runs for outcome in run.outcomes])
        self.proved = np.array([float(outcome.proved) for run in runs for outcome in run.outcomes])
        generator = np.random.default_rng(seed)
        count = len(self.problem_names)
        self.draws = [
            generator.multinomial(count, np.full(count, 1 / count)).astype(float) for _ in range(BOOTSTRAP_SAMPLES)
        ]

    def fit(self, group_of_run: Sequence[int], weights: np.ndarray | None = None) -> Fit:
        groups = np.asarray(group_of_run)[self.run_of_row]
        weights = np.ones(len(self.problem_names)) if weights is None else weights
        return fit_abilities(groups, self.problems, self.proved, weights, max(group_of_run) + 1)

    def percentiles(self, group_of_run: Sequence[int], statistic: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
        """2.5th and 97.5th percentiles of the statistic over the bootstrap draws (rows: lower, upper)."""
        values = np.array([statistic(self.fit(group_of_run, weights).ability) for weights in self.draws])
        return np.percentile(values, [2.5, 97.5], axis=0)


def probe_ratings(found: FinishedRuns, markers: LoopMarkers, seed: int = 0) -> ProbeRatings:
    """The lowest version (version 0, whose runs come first) is the anchor at 0; runs at another expansion budget than
    the most common one are left out, and passes leave out the anchor and the rejected versions."""
    expansion_budget = Counter(run.expansion_budget for run in found.runs).most_common(1)[0][0]
    runs = [run for run in found.runs if run.expansion_budget == expansion_budget]
    rater = Rater(runs, seed)
    version_names = sorted({run.policy_version for run in runs})
    version_index = {version: index for index, version in enumerate(version_names)}
    by_version = [version_index[run.policy_version] for run in runs]
    point = rater.fit(by_version)
    lower, upper = rater.percentiles(by_version, lambda ability: ability)
    anchor = version_names[0]
    budgets = rating_budgets(expansion_budget)
    anchor_by_problem: dict[str, list[ProbeOutcome]] = {}
    for run in runs:
        if run.policy_version == anchor:
            for outcome in run.outcomes:
                anchor_by_problem.setdefault(outcome.problem, []).append(outcome)

    def version_rating(version: int) -> VersionRating:
        own_runs = [run for run in runs if run.policy_version == version]
        own = [outcome for run in own_runs for outcome in run.outcomes]
        searched = sorted({outcome.problem for outcome in own})
        baseline = [anchor_by_problem[problem] for problem in searched if problem in anchor_by_problem]
        index = version_index[version]
        return VersionRating(
            policy_version=version,
            value_version=max(run.value_version for run in own_runs),
            runs=len(own_runs),
            problems=len(searched),
            searches=len(own),
            solved=sum(outcome.proved for outcome in own),
            wall_clock_stops=sum(run.wall_clock_stops for run in own_runs),
            rejected=version in markers.rejected_versions,
            rating=float(point.ability[index]),
            lower=float(lower[index]),
            upper=float(upper[index]),
            projected_solved=projected_solved(float(point.ability[index]), point.difficulty),
            solved_within=tuple(solved_within(own, budget) for budget in budgets),
            baseline_solved_within=tuple(
                float(np.mean([solved_within(outcomes, budget) for outcomes in baseline])) for budget in budgets
            )
            if baseline
            else None,
        )

    parts = sorted({run.part for run in runs if run.part is not None})
    eligible = [
        run for run in runs if run.policy_version != anchor and run.policy_version not in markers.rejected_versions
    ]
    recent = latest_pass(eligible, parts)
    previous = (
        None if recent is None else latest_pass([run for run in eligible if run.name not in names(recent)], parts)
    )
    fix = markers.reward_fix_version
    pre_fix = None if fix is None else latest_pass([run for run in eligible if run.policy_version < fix], parts)

    def pooled(*passes: tuple[ProbeRun, ...]) -> list[int]:
        """Each pass one group after the versions' own; every other run its version's."""
        groups = list(by_version)
        for offset, runs_of_pass in enumerate(passes):
            for index, run in enumerate(runs):
                if run.name in names(runs_of_pass):
                    groups[index] = len(version_names) + offset
        return groups

    def pass_rating(runs_of_pass: tuple[ProbeRun, ...]) -> PassRating:
        groups = pooled(runs_of_pass)
        group = len(version_names)
        fit = rater.fit(groups)
        low, high = rater.percentiles(groups, lambda ability: ability[group])
        return PassRating(
            policy_versions=tuple(run.policy_version for run in runs_of_pass),
            rating=float(fit.ability[group]),
            lower=float(low),
            upper=float(high),
            projected_solved=projected_solved(float(fit.ability[group]), fit.difficulty),
        )

    def comparison(runs_of_pass: tuple[ProbeRun, ...], reference: tuple[ProbeRun, ...] | None) -> PassComparison | None:
        if reference is None or names(runs_of_pass) & names(reference):
            return None
        groups = pooled(runs_of_pass, reference)
        group = len(version_names)
        fit = rater.fit(groups)
        low, high = rater.percentiles(groups, lambda ability: ability[group] - ability[group + 1])
        return PassComparison(
            reference=pass_rating(reference),
            difference=float(fit.ability[group] - fit.ability[group + 1]),
            lower=float(low),
            upper=float(high),
        )

    return ProbeRatings(
        anchor_version=anchor,
        expansion_budget=expansion_budget,
        budgets=budgets,
        problems=len(rater.problem_names),
        baseline_projected_solved=projected_solved(0.0, point.difficulty),
        difficulty_spread=float(np.std(point.difficulty)),
        versions=tuple(version_rating(version) for version in version_names),
        latest_pass=None if recent is None else pass_rating(recent),
        against_previous=None if recent is None else comparison(recent, previous),
        against_pre_fix=None if recent is None else comparison(recent, pre_fix),
        reward_fix_version=fix,
        post_fix_parts=0 if recent is None or fix is None else sum(run.policy_version >= fix for run in recent),
        parts=len(parts),
        runs_rated=len(runs),
        runs_unreadable=found.unreadable,
    )


def record_ratings(run_directory: Path, interval_seconds: float) -> None:
    """Rates again whenever a probe run finishes or the loop's markers change; started beside the dashboard
    (deployment/grpo_loop.sh dashboard). A failed round is logged and retried, so the recorder outlives a bad file."""
    writer = MetricsWriter(run_directory)
    rated: tuple[tuple[str, ...], int, LoopMarkers] | None = None
    while True:
        try:
            found = finished_probe_runs(run_directory / "evaluations")
            markers = read_markers(run_directory)
            key = (tuple(run.name for run in found.runs), found.unreadable, markers)
            if found.runs and key != rated:
                writer.write(probe_ratings(found, markers))
                rated = key
        except Exception:
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
        time.sleep(interval_seconds)
