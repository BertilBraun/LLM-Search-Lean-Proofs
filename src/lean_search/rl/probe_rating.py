"""One rating per version from every finished probe run: logit P(version v proves problem p) = ability_v - difficulty_p.

Each probe slot searches a third of the probe set, so consecutive versions never share problems; the fit estimates each
problem's difficulty from every version that searched it, which puts all versions on one scale against version 0 (an
Elo-like curve on a fixed target). The interval resamples problems. src/lean_search/rl/README.md, "Fixed targets".
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lean_search.monitoring.families import ProbeRatings, VersionRating
from lean_search.monitoring.store import MetricsWriter
from lean_search.rl.evaluation import EvaluationKind, EvaluationPaths, read_summary
from lean_search.search import read_results

# A weak prior on both, so that a version or problem solved every time (or never) keeps a finite estimate.
DIFFICULTY_PRIOR = 0.1
ABILITY_PRIOR = 0.01
NEWTON_STEPS = 100
BOOTSTRAP_SAMPLES = 200


@dataclass(frozen=True)
class ProbeOutcome:
    policy_version: int
    value_version: int
    problem: str
    proved: bool
    # The expansions its first proof took; None when unproved.
    expansions_to_proof: int | None


@dataclass(frozen=True)
class ProbeRun:
    name: str
    expansion_budget: int
    outcomes: tuple[ProbeOutcome, ...]


def finished_probe_runs(evaluations: Path) -> list[ProbeRun]:
    """The probe runs with a summary (a run still searching would rate on its easy problems only), value arms left out:
    they search the same version with another value model."""
    runs = []
    for directory in sorted(evaluations.glob(f"{EvaluationKind.PROBE}_*")):
        paths = EvaluationPaths(directory)
        if not paths.summary.exists() or "_value_arm" in directory.name:
            continue
        summary = read_summary(paths.summary)
        outcomes = tuple(
            ProbeOutcome(
                summary.policy_version,
                summary.value_version,
                result.problem_name,
                result.proved,
                (result.solved_at or result.accounting).expansions if result.proved else None,
            )
            for result in read_results(paths.results)
        )
        runs.append(ProbeRun(directory.name, summary.expansion_budget, outcomes))
    return runs


def fit_abilities(
    versions: np.ndarray, problems: np.ndarray, proved: np.ndarray, weights: np.ndarray, version_count: int
) -> np.ndarray:
    """Newton steps on both parameter blocks (each block's Hessian is diagonal); ability 0 stays the anchor."""
    problem_count = len(weights)
    ability = np.zeros(version_count)
    difficulty = np.zeros(problem_count)
    row_weights = weights[problems]
    for _ in range(NEWTON_STEPS):
        probability = 1 / (1 + np.exp(difficulty[problems] - ability[versions]))
        residual = row_weights * (proved - probability)
        curvature = row_weights * probability * (1 - probability)
        ability_step = (np.bincount(versions, residual, version_count) - ABILITY_PRIOR * ability) / (
            np.bincount(versions, curvature, version_count) + ABILITY_PRIOR
        )
        ability_step[0] = 0.0
        difficulty_step = (-np.bincount(problems, residual, problem_count) - DIFFICULTY_PRIOR * difficulty) / (
            np.bincount(problems, curvature, problem_count) + DIFFICULTY_PRIOR
        )
        ability += np.clip(ability_step, -1.0, 1.0)
        difficulty += np.clip(difficulty_step, -1.0, 1.0)
    return ability


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


def probe_ratings(runs: Sequence[ProbeRun], seed: int = 0) -> ProbeRatings:
    """The lowest version (version 0) is the anchor at 0."""
    outcomes = [outcome for run in runs for outcome in run.outcomes]
    version_names = sorted({outcome.policy_version for outcome in outcomes})
    problem_names = sorted({outcome.problem for outcome in outcomes})
    version_index = {version: index for index, version in enumerate(version_names)}
    problem_index = {problem: index for index, problem in enumerate(problem_names)}
    versions = np.array([version_index[outcome.policy_version] for outcome in outcomes])
    problems = np.array([problem_index[outcome.problem] for outcome in outcomes])
    proved = np.array([float(outcome.proved) for outcome in outcomes])
    ability = fit_abilities(versions, problems, proved, np.ones(len(problem_names)), len(version_names))
    generator = np.random.default_rng(seed)
    resampled = np.array(
        [
            fit_abilities(
                versions,
                problems,
                proved,
                generator.multinomial(len(problem_names), np.full(len(problem_names), 1 / len(problem_names))).astype(
                    float
                ),
                len(version_names),
            )
            for _ in range(BOOTSTRAP_SAMPLES)
        ]
    )
    lower, upper = np.percentile(resampled, [2.5, 97.5], axis=0)
    budgets = rating_budgets(max(run.expansion_budget for run in runs))
    baseline_version = version_names[0]
    baseline_by_problem: dict[str, list[ProbeOutcome]] = {}
    for outcome in outcomes:
        if outcome.policy_version == baseline_version:
            baseline_by_problem.setdefault(outcome.problem, []).append(outcome)
    rated = []
    for version in version_names:
        own = [outcome for outcome in outcomes if outcome.policy_version == version]
        searched = sorted({outcome.problem for outcome in own})
        baseline = [baseline_by_problem[problem] for problem in searched if problem in baseline_by_problem]
        index = version_index[version]
        rated.append(
            VersionRating(
                policy_version=version,
                value_version=max(outcome.value_version for outcome in own),
                runs=sum(any(outcome.policy_version == version for outcome in run.outcomes) for run in runs),
                problems=len(searched),
                searches=len(own),
                solved=sum(outcome.proved for outcome in own),
                rating=float(ability[index]),
                lower=float(lower[index]),
                upper=float(upper[index]),
                solved_within=tuple(solved_within(own, budget) for budget in budgets),
                baseline_solved_within=tuple(
                    float(np.mean([solved_within(runs_of_problem, budget) for runs_of_problem in baseline]))
                    if baseline
                    else 0.0
                    for budget in budgets
                ),
            )
        )
    latest = rated[-1]
    return ProbeRatings(
        budgets=budgets,
        versions=tuple(rated),
        latest_policy_version=latest.policy_version,
        latest_rating=latest.rating,
        latest_lower=latest.lower,
        latest_upper=latest.upper,
    )


def record_ratings(run_directory: Path, interval_seconds: float) -> None:
    """Rates again whenever a probe run finishes; started beside the dashboard (deployment/grpo_loop.sh dashboard)."""
    writer = MetricsWriter(run_directory)
    rated: tuple[str, ...] = ()
    while True:
        runs = finished_probe_runs(run_directory / "evaluations")
        names = tuple(run.name for run in runs)
        if runs and names != rated:
            writer.write(probe_ratings(runs))
            rated = names
        time.sleep(interval_seconds)
