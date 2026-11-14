"""Evaluation noise floor of grpo_loop_v1 from its recorded evaluations, to size the follow-up's probe.

Reads the published evaluations (probe thirds, held-out states), the probe's fixed set and the verified pool's proof
lengths. Prints the tables of results/followup_step0/noise_floor.md.

    PYTHONPATH=src python experiments/analysis/noise_floor.py [--dataset node_backup/2026-11-01/hf_dataset]
"""

import argparse
import json
import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lean_search.rl.probe_rating import ProbeRun, finished_probe_runs
from lean_search.rl.single_step import root_samples
from lean_search.search.records import read_results, read_tree

CHARACTER_EDGES = (0, 500, 1000, 1500, 2000, 3000, 4500)
CHARACTER_LABELS = ("0-499", "500-999", "1,000-1,499", "1,500-1,999", "2,000-2,999", "3,000-4,499", "4,500+")
NEW_PROBE_COUNTS = (150, 250, 350, 350, 400, 300, 200)
BUDGETS = (1, 2, 4, 8, 16)
TACTIC_STRATA = ("easy", "medium", "hard")
QUADRATURE_POINTS = 24
SIGMA_GRID = np.arange(0.2, 8.0, 0.05)
MU_GRID = np.arange(-10.0, 10.0, 0.02)
TAU_GRID = np.arange(0.0, 3.01, 0.05)
SHIFT_GRID = np.arange(-0.2, 0.81, 0.04)
SIMULATION_REPEATS = 1500
Z_CRITICAL = 1.959964
TARGET_POWER = 0.8
NORMAL_NODES, NORMAL_WEIGHTS = np.polynomial.hermite_e.hermegauss(QUADRATURE_POINTS)
NORMAL_WEIGHTS = NORMAL_WEIGHTS / NORMAL_WEIGHTS.sum()


@dataclass(frozen=True)
class Statement:
    name: str
    stratum: str
    characters_bin: int


@dataclass(frozen=True)
class Outcome:
    proved_at: int | None
    # Expansions the search spent: up to its proof, or all it ran when unproved.
    expansions: int

    def solved_within(self, budget: int) -> bool:
        return self.proved_at is not None and self.proved_at <= budget

    def cost_within(self, budget: int) -> int:
        return min(self.expansions, budget)


@dataclass(frozen=True)
class Run:
    name: str
    version: int
    part: int
    outcomes: dict[str, Outcome]


@dataclass(frozen=True)
class PairCounts:
    problems: int
    first_solved: int
    second_solved: int
    only_first: int
    only_second: int

    @property
    def discordant(self) -> int:
        return self.only_first + self.only_second

    @property
    def mcnemar_p(self) -> float:
        return exact_mcnemar(self.only_first, self.only_second)


@dataclass(frozen=True)
class LogitModel:
    """v0's per-statement solve logit at 16 expansions: normal per proof-length bin, one spread for all bins."""

    means: np.ndarray
    spread: float
    spread_low: float
    spread_high: float


@dataclass(frozen=True)
class PairFit:
    shift: float
    divergence: float


@dataclass(frozen=True)
class HeldOutState:
    samples: int
    valid: int
    proved: int


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as lines:
        yield from (json.loads(line) for line in lines if line.strip())


def statement_name(statement: dict) -> str:
    return f"{statement['source']}.{statement['identifier']}".replace("/", "_")


def characters_bin(characters: int) -> int:
    return sum(characters >= edge for edge in CHARACTER_EDGES) - 1


def read_statements(dataset: Path) -> dict[str, Statement]:
    probe = {
        statement_name(record["statement"]): record["stratum"]
        for record in read_jsonl(dataset / "fixed_sets" / "fixed_sets" / "probe.jsonl")
    }
    characters = {
        statement_name(record["statement"]): record["proof_characters"]
        for record in read_jsonl(dataset / "verified_pool" / "verified.jsonl")
        if statement_name(record["statement"]) in probe
    }
    assert len(characters) == len(probe), "every probe statement has a verified proof in the pool"
    return {name: Statement(name, stratum, characters_bin(characters[name])) for name, stratum in probe.items()}


def read_runs(evaluations: Path) -> list[Run]:
    """Probe runs in the order they finished, with the expansions each search spent (results.jsonl)."""
    runs = []
    for probe_run in finished_probe_runs(evaluations).runs:
        spent = {
            result.problem_name: result.accounting.expansions
            for result in read_results(evaluations / probe_run.name / "results.jsonl")
        }
        runs.append(run_of(probe_run, spent))
    return runs


def run_of(probe_run: ProbeRun, spent: dict[str, int]) -> Run:
    assert probe_run.part is not None
    outcomes = {
        outcome.problem: Outcome(outcome.expansions_to_proof, outcome.expansions_to_proof or spent[outcome.problem])
        for outcome in probe_run.outcomes
    }
    return Run(probe_run.name, probe_run.policy_version, probe_run.part, outcomes)


def exact_mcnemar(only_first: int, only_second: int) -> float:
    discordant = only_first + only_second
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, count) for count in range(min(only_first, only_second) + 1)) / 2**discordant
    return min(1.0, 2 * tail)


def pair_counts(first: Run, second: Run, names: Sequence[str], budget: int = 16) -> PairCounts:
    first_solved = [first.outcomes[name].solved_within(budget) for name in names]
    second_solved = [second.outcomes[name].solved_within(budget) for name in names]
    return PairCounts(
        len(names),
        sum(first_solved),
        sum(second_solved),
        sum(a and not b for a, b in zip(first_solved, second_solved, strict=True)),
        sum(b and not a for a, b in zip(first_solved, second_solved, strict=True)),
    )


def print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    print("| " + " | ".join(headers) + " |")
    print("|" + "---|" * len(headers))
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")
    print()


def sigmoid(values: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-values))


def counts_by_bin(statements: Sequence[Statement], pairs: Sequence[tuple[bool, bool]]) -> np.ndarray:
    """Per proof-length bin, statements solved in 0, 1 and 2 of the two runs."""
    counts = np.zeros((len(CHARACTER_EDGES), 3))
    for statement, (first, second) in zip(statements, pairs, strict=True):
        counts[statement.characters_bin, first + second] += 1
    return counts


def fit_logit_model(counts: np.ndarray) -> LogitModel:
    """Maximum likelihood over a grid; the spread's interval is where the profile log-likelihood drops by 1.92."""
    profile = []
    best_means = []
    for spread in SIGMA_GRID:
        probability = sigmoid(MU_GRID[:, None] + spread * NORMAL_NODES[None, :])
        moments = np.stack(
            [
                (probability**solved * (1 - probability) ** (2 - solved)) @ NORMAL_WEIGHTS * (2 if solved == 1 else 1)
                for solved in range(3)
            ],
            axis=1,
        )
        likelihood = counts @ np.log(moments).T
        profile.append(likelihood.max(axis=1).sum())
        best_means.append(MU_GRID[likelihood.argmax(axis=1)])
    profile_array = np.array(profile)
    best = int(profile_array.argmax())
    inside = SIGMA_GRID[profile_array >= profile_array[best] - 1.92]
    return LogitModel(best_means[best], float(SIGMA_GRID[best]), float(inside.min()), float(inside.max()))


@dataclass(frozen=True)
class PairMoments:
    first_rate: float
    second_rate: float
    discordance: float


def pair_moments(means: np.ndarray, spread: float, weights: np.ndarray, shift: float, divergence: float) -> PairMoments:
    """First run logit ~ N(mean of its bin, spread^2), the second's = first + shift + N(0, divergence^2), each run one
    Bernoulli draw: expected solve rates and discordance over bins weighted by `weights`."""
    first = sigmoid(means[:, None, None] + spread * NORMAL_NODES[None, :, None])
    second = sigmoid(
        means[:, None, None] + spread * NORMAL_NODES[None, :, None] + shift + divergence * NORMAL_NODES[None, None, :]
    )
    grid_weights = NORMAL_WEIGHTS[:, None] * NORMAL_WEIGHTS[None, :]
    share = weights / weights.sum()
    return PairMoments(
        float(share @ (first * grid_weights).sum(axis=(1, 2))),
        float(share @ (second * grid_weights).sum(axis=(1, 2))),
        float(share @ ((first * (1 - second) + second * (1 - first)) * grid_weights).sum(axis=(1, 2))),
    )


def fit_pair(means: np.ndarray, spread: float, weights: np.ndarray, second_rate: float, discordance: float) -> PairFit:
    """Shift matching the second rate, divergence matching the discordance (0 when search noise alone explains it)."""

    def shift_for(divergence: float) -> float:
        low, high = -6.0, 6.0
        for _ in range(40):
            middle = (low + high) / 2
            if pair_moments(means, spread, weights, middle, divergence).second_rate < second_rate:
                low = middle
            else:
                high = middle
        return (low + high) / 2

    best = PairFit(shift_for(0.0), 0.0)
    for divergence in TAU_GRID:
        shift = shift_for(float(divergence))
        if pair_moments(means, spread, weights, shift, float(divergence)).discordance > discordance:
            break
        best = PairFit(shift, float(divergence))
    return best


def bin_weights(statements: Sequence[Statement]) -> np.ndarray:
    return np.bincount([statement.characters_bin for statement in statements], minlength=len(CHARACTER_EDGES)).astype(
        float
    )


@dataclass(frozen=True)
class Scenario:
    label: str
    base_means: np.ndarray
    base_spread: float
    divergence: float


def simulated_power(
    scenario: Scenario, statements: int, repeats: int, generator: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Power and expected difference (points) per logit shift of arm B over arm A, paired per statement: McNemar's z
    for one run per arm, a paired z on per-statement means for several."""
    per_bin = np.round(np.array(NEW_PROBE_COUNTS) * statements / sum(NEW_PROBE_COUNTS)).astype(int)
    bin_of_statement = np.repeat(np.arange(len(per_bin)), per_bin)
    count = len(bin_of_statement)
    powers = []
    differences = []
    for shift in SHIFT_GRID:
        first_logit = scenario.base_means[bin_of_statement] + scenario.base_spread * generator.standard_normal(
            (SIMULATION_REPEATS, count)
        )
        second_logit = (
            first_logit + shift + scenario.divergence * generator.standard_normal((SIMULATION_REPEATS, count))
        )
        first = sigmoid(first_logit)
        second = sigmoid(second_logit)
        first_mean = np.mean([generator.random(first.shape) < first for _ in range(repeats)], axis=0)
        second_mean = np.mean([generator.random(second.shape) < second for _ in range(repeats)], axis=0)
        difference = second_mean - first_mean
        standard_error = difference.std(axis=1, ddof=1) / math.sqrt(count)
        z = difference.mean(axis=1) / np.maximum(standard_error, 1e-12)
        powers.append(float(np.mean(z > Z_CRITICAL)))
        differences.append(float(100 * (second - first).mean()))
    return np.array(powers), np.array(differences)


def detectable_difference(powers: np.ndarray, differences: np.ndarray) -> float:
    above = np.nonzero(powers >= TARGET_POWER)[0]
    index = int(above[0])
    if index == 0:
        return float(differences[0])
    fraction = (TARGET_POWER - powers[index - 1]) / (powers[index] - powers[index - 1])
    return float(differences[index - 1] + fraction * (differences[index] - differences[index - 1]))


def read_held_out(evaluations: Path, version: int) -> dict[str, HeldOutState]:
    states = {}
    for path in sorted((evaluations / f"held_out_states_v{version:04d}" / "trees").glob("*.json.gz")):
        samples = root_samples(read_tree(path, texts=False), frozenset())
        states[path.name] = HeldOutState(
            sum(sample.sample_count for sample in samples),
            sum(sample.sample_count for sample in samples if sample.valid),
            sum(sample.sample_count for sample in samples if sample.success),
        )
    return states


def binomial_deviation(rate: float, samples: int) -> float:
    return 100 * math.sqrt(rate * (1 - rate) / samples)


def within_state_deviation(states: dict[str, HeldOutState], count: Callable[[HeldOutState], int]) -> float:
    """Run-to-run SD (points) of the pooled rate from resampling each state's samples (x(n-x)/(n-1) per state)."""
    total = sum(state.samples for state in states.values())
    variance = sum(
        count(state) * (state.samples - count(state)) / (state.samples - 1)
        for state in states.values()
        if state.samples > 1
    )
    return 100 * math.sqrt(variance) / total


def paired_state_deviation(
    first: dict[str, HeldOutState], second: dict[str, HeldOutState], count: Callable[[HeldOutState], int]
) -> float:
    """SD (points) of the mean per-state rate difference, paired per state (states without samples left out)."""
    differences = [
        count(second[name]) / second[name].samples - count(first[name]) / first[name].samples
        for name in first
        if first[name].samples and second[name].samples
    ]
    return 100 * float(np.std(differences, ddof=1)) / math.sqrt(len(differences))


def report_same_model(statements: dict[str, Statement], runs: Sequence[Run]) -> None:
    print("## 1. v0 twice: same model, same third\n")
    rows = []
    for part in range(3):
        first, second = [run for run in runs if run.version == 0 and run.part == part]
        names = sorted(first.outcomes)
        counts = pair_counts(first, second, names)
        rows.append(
            (
                part,
                counts.problems,
                f"{counts.first_solved} / {counts.second_solved}",
                f"{counts.only_first} / {counts.only_second}",
                f"{counts.mcnemar_p:.2f}",
            )
        )
    print_table(("third", "problems", "solved run 1 / 2", "only run 1 / only 2", "exact McNemar p"), rows)
    v0_runs = [run for run in runs if run.version == 0]
    pairs_by_part = {part: tuple(run for run in v0_runs if run.part == part) for part in range(3)}

    def grouped(key: Callable[[Statement], object], labels: Sequence[object], budget: int) -> list[tuple]:
        result = []
        for label in labels:
            problems = solved_both = solved_once = 0
            solved_runs = 0
            for first, second in pairs_by_part.values():
                for name in first.outcomes:
                    if key(statements[name]) != label:
                        continue
                    a = first.outcomes[name].solved_within(budget)
                    b = second.outcomes[name].solved_within(budget)
                    problems += 1
                    solved_both += a and b
                    solved_once += a != b
                    solved_runs += a + b
            mean = solved_runs / (2 * problems)
            random_share = (solved_once / (2 * problems)) / (mean * (1 - mean)) if 0 < mean < 1 else float("nan")
            result.append(
                (
                    label,
                    problems,
                    f"{100 * mean:.0f}%",
                    f"{100 * solved_both / problems:.0f}% / {100 * solved_once / problems:.0f}%",
                    f"{100 * (problems - solved_both - solved_once) / problems:.0f}%",
                    f"{math.sqrt(solved_once / 2):.1f} ({100 * math.sqrt(solved_once / 2) / problems:.1f})",
                    f"{random_share:.2f}",
                )
            )
        return result

    headers = (
        "group",
        "problems",
        "mean solved",
        "both / one run",
        "neither",
        "SD of a count from search (points)",
        "coin-flip share",
    )
    print("### By tactic stratum and by proof characters (16 expansions, three thirds pooled)\n")
    print_table(
        headers,
        grouped(lambda statement: statement.stratum, TACTIC_STRATA, 16)
        + grouped(lambda statement: CHARACTER_LABELS[statement.characters_bin], CHARACTER_LABELS, 16)
        + grouped(lambda statement: "all", ("all",), 16),
    )
    print("### All 501 by budget (solved within k expansions of the same runs)\n")
    print_table(
        ("budget", *headers[1:]),
        [(budget, *grouped(lambda statement: "all", ("all",), budget)[0][1:]) for budget in BUDGETS],
    )


def later_pairs(runs: Sequence[Run]) -> list[tuple[str, Run, Run]]:
    """(kind, earlier, later) on the same third: v0's first run against each later version, and neighbours."""
    pairs = []
    for part in range(3):
        on_part = [run for run in runs if run.part == part]
        v0_first = on_part[0]
        later = [run for run in on_part if run.version != 0]
        pairs += [("v0", v0_first, run) for run in later]
        pairs += [("neighbour", earlier, run) for earlier, run in zip(later, later[1:], strict=False)]
    return pairs


def v0_discordance(runs: Sequence[Run], later: Run) -> float:
    v0 = [run for run in runs if run.version == 0 and run.part == later.part]
    names = sorted(later.outcomes)
    return float(np.mean([pair_counts(run, later, names).discordant for run in v0])) / len(names)


def report_version_pairs(
    statements: dict[str, Statement], runs: Sequence[Run], model: LogitModel
) -> tuple[list[float], list[float], list[PairFit]]:
    print("## 2. Different versions on the same third (16 expansions)\n")
    rows = []
    differences = []
    discordances = []
    divergence_fits: dict[int, PairFit] = {}
    neighbour_fits = []
    for kind, earlier, later in later_pairs(runs):
        names = sorted(later.outcomes)
        counts = pair_counts(earlier, later, names)
        weights = bin_weights([statements[name] for name in names])
        match kind:
            case "v0":
                discordance = v0_discordance(runs, later)
                fit = fit_pair(model.means, model.spread, weights, counts.second_solved / counts.problems, discordance)
                divergence_fits[later.version] = fit
            case _:
                discordance = counts.discordant / counts.problems
                base = divergence_fits[earlier.version]
                fit = fit_pair(
                    model.means + base.shift,
                    math.hypot(model.spread, base.divergence),
                    weights,
                    counts.second_solved / counts.problems,
                    discordance,
                )
                neighbour_fits.append(fit)
        differences.append(100 * (counts.second_solved - counts.first_solved) / counts.problems)
        discordances.append(100 * counts.discordant / counts.problems)
        rows.append(
            (
                later.part,
                f"v{earlier.version} -> v{later.version}",
                f"{counts.first_solved} -> {counts.second_solved}",
                f"{differences[-1]:+.1f}",
                f"{counts.only_first} / {counts.only_second}",
                f"{discordances[-1]:.0f}%",
                f"{discordances[-1] - abs(differences[-1]):.0f}",
                f"{counts.mcnemar_p:.3f}",
                f"{fit.divergence:.2f}",
            )
        )
    print_table(
        (
            "third",
            "pair",
            "solved",
            "points",
            "lost / gained",
            "discordant",
            "discordant beyond |points|",
            "exact McNemar p",
            "fitted divergence (logit SD)",
        ),
        rows,
    )
    slope, intercept = np.polyfit(np.abs(differences), discordances, 1)
    print(
        f"Discordant share = {intercept:.1f}% + {slope:.2f} x |points| (least squares over {len(rows)} pairs); "
        f"v0 against itself: see section 1.\n"
    )
    return differences, discordances, neighbour_fits + list(divergence_fits.values())


def report_minif2f(evaluations: Path) -> None:
    solved = [
        {result.problem_name: result.proved for result in read_results(evaluations / name / "results.jsonl")}
        for name in ("minif2f_v0000", "minif2f_v0035")
    ]
    names = sorted(solved[0])
    lost = sum(solved[0][name] and not solved[1][name] for name in names)
    gained = sum(solved[1][name] and not solved[0][name] for name in names)
    print(
        f"miniF2F-valid (64 expansions) v0 -> v35: {sum(solved[0].values())} -> {sum(solved[1].values())} of "
        f"{len(names)}, lost / gained {lost} / {gained}, exact McNemar p {exact_mcnemar(lost, gained):.3f}\n"
    )


def report_budgets(runs: Sequence[Run]) -> None:
    print("## 6a. Information per expansion by budget (v0's runs against every later version on their third)\n")
    rows = []
    reference = None
    for budget in BUDGETS:
        squared_z = []
        costs = []
        for run in runs:
            if run.version == 0:
                continue
            names = sorted(run.outcomes)
            for v0 in [other for other in runs if other.version == 0 and other.part == run.part]:
                counts = pair_counts(v0, run, names, budget)
                squared_z.append((counts.only_second - counts.only_first) ** 2 / max(counts.discordant, 1))
                costs.append(
                    np.mean([v0.outcomes[name].cost_within(budget) for name in names])
                    + np.mean([run.outcomes[name].cost_within(budget) for name in names])
                )
        information = float(np.mean(squared_z))
        cost = float(np.mean(costs)) / 2
        per_cost = information / cost
        reference = per_cost if budget == BUDGETS[-1] else reference
        rows.append((budget, f"{cost:.1f}", f"{information:.1f}", f"{per_cost:.2f}"))
    rows = [(*row, f"{float(row[3]) / reference:.2f}") for row in rows]
    print_table(
        (
            "budget",
            "expansions per statement",
            "mean McNemar z^2 (26 pairs)",
            "z^2 per expansion per statement",
            "relative to 16",
        ),
        rows,
    )


def report_power(model: LogitModel, fits: Sequence[PairFit], generator: np.random.Generator) -> None:
    print("## 3. Detectable difference on the new probe (80% power, 5% two-sided, paired per statement)\n")
    kept = sorted(fit.divergence for fit in fits)
    trained_shift = float(np.median([fit.shift for fit in fits]))
    scenarios = [
        Scenario("v0-like arms, divergence 0", model.means, model.spread, 0.0),
        Scenario(
            f"trained arms (+{trained_shift:.2f} logit), divergence {np.median(kept):.2f} (median pair)",
            model.means + trained_shift,
            model.spread,
            float(np.median(kept)),
        ),
        Scenario(
            f"trained arms, divergence {kept[-1]:.2f} (largest pair)",
            model.means + trained_shift,
            model.spread,
            kept[-1],
        ),
        Scenario(
            f"trained arms, divergence {np.median(kept):.2f}, v0 spread {model.spread_low:.1f} (low end)",
            model.means + trained_shift,
            model.spread_low,
            float(np.median(kept)),
        ),
        Scenario(
            f"trained arms, divergence {np.median(kept):.2f}, v0 spread {model.spread_high:.1f} (high end)",
            model.means + trained_shift,
            model.spread_high,
            float(np.median(kept)),
        ),
    ]
    rows = []
    for scenario in scenarios:
        cells = []
        for statements in (1000, 2000, 4000):
            for repeats in (1, 2):
                powers, differences = simulated_power(scenario, statements, repeats, generator)
                cells.append(f"{detectable_difference(powers, differences):.1f}")
        moments = pair_moments(
            scenario.base_means, scenario.base_spread, np.array(NEW_PROBE_COUNTS, dtype=float), 0.0, scenario.divergence
        )
        rows.append((scenario.label, f"{100 * moments.first_rate:.0f}%", f"{100 * moments.discordance:.0f}%", *cells))
    print_table(
        (
            "scenario",
            "arm A solved",
            "discordant at no difference",
            "1,000 x1",
            "1,000 x2",
            "2,000 x1",
            "2,000 x2",
            "4,000 x1",
            "4,000 x2",
        ),
        rows,
    )


def report_held_out(evaluations: Path) -> None:
    print("## 4. Held-out states (one expansion of 8 samples per state, 512 states)\n")
    summaries = {
        record["policy_version"]: record
        for record in read_jsonl(evaluations / "evaluations.jsonl")
        if record["kind"] == "held_out_states"
    }
    versions = (0, 25, 27, 28, 29, 30, 33, 35)
    states = {version: read_held_out(evaluations, version) for version in versions}
    rows = []
    for version in versions:
        summary = summaries[version]
        own = states[version]
        samples = sum(state.samples for state in own.values())
        valid = sum(state.valid for state in own.values())
        proved = sum(state.proved for state in own.values())
        success = summary["solved"] / summary["samples"]
        rows.append(
            (
                f"v{version}",
                f"{samples} ({summary['samples']})",
                f"{100 * success:.1f}% ± {binomial_deviation(success, samples):.2f}",
                f"{100 * valid / samples:.1f}% ± {binomial_deviation(valid / samples, samples):.2f}"
                f" / {within_state_deviation(own, lambda state: state.valid):.2f}",
                f"{100 * proved / samples:.1f}% ± {within_state_deviation(own, lambda state: state.proved):.2f}",
            )
        )
    print_table(
        (
            "version",
            "samples (summary)",
            "success ± binomial SD",
            "valid ± binomial / within-state SD",
            "proved ± within-state SD",
        ),
        rows,
    )
    pair_rows = []
    for first, second in ((27, 28), (28, 29), (29, 30), (27, 29), (0, 35), (25, 27), (33, 35)):
        a, b = states[first], states[second]
        valid_difference = 100 * (
            sum(state.valid for state in b.values()) / sum(state.samples for state in b.values())
            - sum(state.valid for state in a.values()) / sum(state.samples for state in a.values())
        )
        valid_deviation = paired_state_deviation(a, b, lambda state: state.valid)
        proved_deviation = paired_state_deviation(a, b, lambda state: state.proved)
        pair_rows.append(
            (
                f"v{first} -> v{second}",
                f"{valid_difference:+.1f}",
                f"{valid_deviation:.2f} ({2.80 * valid_deviation:.1f})",
                f"{proved_deviation:.2f} ({2.80 * proved_deviation:.1f})",
            )
        )
    print_table(
        (
            "pair",
            "valid points (pooled)",
            "valid: SE of paired per-state mean (80% detectable)",
            "proved: SE (80% detectable)",
        ),
        pair_rows,
    )


def report_seed_proxy(runs: Sequence[Run]) -> None:
    print("## 5. Neighbouring kept versions on one third: change against eval noise\n")
    rows = []
    for _, earlier, later in later_pairs(runs):
        if earlier.version < 13 or later.version > 25:
            continue
        names = sorted(later.outcomes)
        counts = pair_counts(earlier, later, names)
        noise = math.sqrt(counts.discordant)
        change = counts.second_solved - counts.first_solved
        rows.append(
            (
                f"v{earlier.version} -> v{later.version}",
                f"{100 * change / counts.problems:+.1f}",
                f"{100 * noise / counts.problems:.1f}",
                f"{change / noise:+.1f}",
            )
        )
    print_table(("pair", "points", "SD of the paired difference (points)", "z"), rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("node_backup/2026-11-01/hf_dataset"))
    parser.add_argument("--seed", type=int, default=0)
    arguments = parser.parse_args()
    evaluations = arguments.dataset / "evaluations"
    statements = read_statements(arguments.dataset)
    runs = read_runs(evaluations)
    generator = np.random.default_rng(arguments.seed)

    report_same_model(statements, runs)
    v0_pairs = []
    v0_statements = []
    for part in range(3):
        first, second = [run for run in runs if run.version == 0 and run.part == part]
        for name in first.outcomes:
            v0_statements.append(statements[name])
            v0_pairs.append((first.outcomes[name].solved_within(16), second.outcomes[name].solved_within(16)))
    counts = counts_by_bin(v0_statements, v0_pairs)
    model = fit_logit_model(counts)
    print(
        f"Logit-normal fit to v0's two runs: spread {model.spread:.2f} (95% {model.spread_low:.2f}-"
        f"{model.spread_high:.2f}), bin means {np.round(model.means, 2).tolist()}"
    )
    expected = [
        pair_moments(model.means[[index]], model.spread, np.ones(1), 0.0, 0.0).discordance * counts[index].sum()
        for index in range(len(CHARACTER_EDGES))
    ]
    print(f"discordant per bin observed {counts[:, 1].astype(int).tolist()}, fitted {np.round(expected, 1).tolist()}\n")
    _, _, fits = report_version_pairs(statements, runs, model)
    report_minif2f(evaluations)
    report_seed_proxy(runs)
    report_budgets(runs)
    report_power(model, fits, generator)
    report_held_out(evaluations)


if __name__ == "__main__":
    main()
