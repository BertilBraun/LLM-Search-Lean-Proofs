"""Run summaries: solve rates by category, anytime (solve-rate-vs-budget) curves and cost statistics."""

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.search.search import Accounting, SearchConfig, SearchResult, StepStatistics, StopReason

CATEGORIES = (
    "mathd_algebra",
    "mathd_numbertheory",
    "amc12",
    "aime",
    "imo",
    "algebra",
    "numbertheory",
    "induction",
)
SECONDS_BUDGETS = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 180.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0)


class CostMetric(StrEnum):
    EXPANSIONS = "expansions"
    WALL_SECONDS = "wall_seconds"
    LEAN_SECONDS = "lean_seconds"
    NODES = "nodes"
    EDGES = "edges"
    DUPLICATES = "duplicates"
    ERRORS = "errors"
    TIMEOUTS = "timeouts"
    VERIFICATION_SECONDS = "verification_seconds"
    GENERATED_TOKENS = "generated_tokens"

    def of(self, accounting: Accounting) -> float:
        match self:
            case CostMetric.EXPANSIONS:
                return accounting.expansions
            case CostMetric.WALL_SECONDS:
                return accounting.wall_seconds
            case CostMetric.LEAN_SECONDS:
                return accounting.lean_seconds
            case CostMetric.NODES:
                return accounting.nodes
            case CostMetric.EDGES:
                return accounting.edges
            case CostMetric.DUPLICATES:
                return accounting.duplicates
            case CostMetric.ERRORS:
                return accounting.errors
            case CostMetric.TIMEOUTS:
                return accounting.timeouts
            case CostMetric.VERIFICATION_SECONDS:
                return accounting.verification_seconds
            case CostMetric.GENERATED_TOKENS:
                return accounting.generated_tokens


COST_METRICS = (
    CostMetric.EXPANSIONS,
    CostMetric.NODES,
    CostMetric.EDGES,
    CostMetric.LEAN_SECONDS,
    CostMetric.WALL_SECONDS,
    CostMetric.DUPLICATES,
    CostMetric.ERRORS,
    CostMetric.TIMEOUTS,
    CostMetric.VERIFICATION_SECONDS,
)


@dataclass(frozen=True)
class CurvePoint:
    budget: float
    solved: int
    solve_rate: float


@dataclass(frozen=True)
class AnytimeCurve:
    metric: CostMetric
    points: tuple[CurvePoint, ...]


@dataclass(frozen=True)
class CategoryResult:
    category: str
    problems: int
    solved: int
    solve_rate: float


@dataclass(frozen=True)
class StopReasonCount:
    stop_reason: StopReason
    problems: int


@dataclass(frozen=True)
class Distribution:
    metric: CostMetric
    mean: float
    median: float
    p90: float
    maximum: float
    total: float


@dataclass(frozen=True)
class CostTable:
    group: str
    problems: int
    distributions: tuple[Distribution, ...]


@dataclass(frozen=True)
class StepCost:
    step: str
    attempts: int
    lean_seconds: float
    lean_seconds_fraction: float
    mean_seconds: float
    children: int
    duplicates: int
    failures: int
    errors: int
    heartbeat_timeouts: int
    wall_clock_timeouts: int
    rejected: int
    closing: int
    on_proof_paths: int


@dataclass(frozen=True)
class DepthCount:
    depth: int
    solved: int


@dataclass(frozen=True)
class SolvedProof:
    problem_name: str
    proof_steps: tuple[str, ...]


@dataclass(frozen=True)
class RunMetadata:
    run_name: str
    split: str
    git_revision: str
    git_dirty: bool
    config_file: str
    started_at: str
    run_wall_seconds: float
    cpu_count: int
    load_average_at_start: float


@dataclass(frozen=True)
class RunSummary:
    metadata: RunMetadata
    problems: int
    solved: int
    solve_rate: float
    categories: tuple[CategoryResult, ...]
    stop_reasons: tuple[StopReasonCount, ...]
    curves: tuple[AnytimeCurve, ...]
    costs: tuple[CostTable, ...]
    steps: tuple[StepCost, ...]
    proof_depths: tuple[DepthCount, ...]
    solved_at_depth_two_or_more: int
    multi_step_proofs: tuple[SolvedProof, ...]
    verification_failures: int
    start_failures: int


def category(problem_name: str) -> str:
    return next((prefix for prefix in CATEGORIES if problem_name.startswith(prefix)), "other")


def anytime_curve(results: Sequence[SearchResult], metric: CostMetric, budgets: Sequence[float]) -> AnytimeCurve:
    """A theorem counts as solved at budget b if the search had spent at most b when the proof was found."""
    costs = [metric.of(result.solved_at) for result in results if result.solved_at is not None]
    points = []
    for budget in budgets:
        solved = sum(cost <= budget for cost in costs)
        points.append(CurvePoint(budget, solved, solved / len(results)))
    return AnytimeCurve(metric, tuple(points))


def expansion_budgets(max_expansions: int) -> tuple[float, ...]:
    budgets = [float(2**exponent) for exponent in range(max_expansions.bit_length()) if 2**exponent < max_expansions]
    return (*budgets, float(max_expansions))


def seconds_budgets(max_seconds: float) -> tuple[float, ...]:
    return (*(budget for budget in SECONDS_BUDGETS if budget < max_seconds), max_seconds)


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def distribution(metric: CostMetric, accountings: Sequence[Accounting]) -> Distribution:
    values = [metric.of(accounting) for accounting in accountings]
    return Distribution(
        metric,
        statistics.fmean(values),
        statistics.median(values),
        percentile(values, 0.9),
        max(values),
        sum(values),
    )


def cost_table(group: str, accountings: Sequence[Accounting]) -> CostTable:
    distributions = tuple(distribution(metric, accountings) for metric in COST_METRICS) if accountings else ()
    return CostTable(group, len(accountings), distributions)


def step_costs(results: Sequence[SearchResult]) -> tuple[StepCost, ...]:
    totals: dict[str, StepStatistics] = {}
    for result in results:
        for step in result.step_statistics:
            total = totals.setdefault(step.step, StepStatistics(step.step))
            total.attempts += step.attempts
            total.lean_seconds += step.lean_seconds
            total.children += step.children
            total.duplicates += step.duplicates
            total.errors += step.errors
            total.heartbeat_timeouts += step.heartbeat_timeouts
            total.wall_clock_timeouts += step.wall_clock_timeouts
            total.rejected += step.rejected
            total.repeated += step.repeated
            total.proofs += step.proofs
    on_proof_paths = Counter(step for result in results for step in result.proof_steps)
    all_lean_seconds = sum(total.lean_seconds for total in totals.values()) or 1.0
    costs = (
        StepCost(
            step=total.step,
            attempts=total.attempts,
            lean_seconds=total.lean_seconds,
            lean_seconds_fraction=total.lean_seconds / all_lean_seconds,
            mean_seconds=total.lean_seconds / max(total.attempts, 1),
            children=total.children,
            duplicates=total.duplicates,
            failures=total.attempts - total.children - total.duplicates - total.repeated,
            errors=total.errors,
            heartbeat_timeouts=total.heartbeat_timeouts,
            wall_clock_timeouts=total.wall_clock_timeouts,
            rejected=total.rejected,
            closing=total.proofs,
            on_proof_paths=on_proof_paths[total.step],
        )
        for total in totals.values()
    )
    return tuple(sorted(costs, key=lambda cost: -cost.lean_seconds))


def summarize(results: Sequence[SearchResult], metadata: RunMetadata, search_config: SearchConfig) -> RunSummary:
    if not results:
        raise ValueError("No results to summarize.")
    solved = [result for result in results if result.proved]
    by_category: dict[str, list[SearchResult]] = {}
    for result in results:
        by_category.setdefault(category(result.problem_name), []).append(result)
    categories = tuple(
        CategoryResult(
            name,
            len(members),
            sum(member.proved for member in members),
            sum(member.proved for member in members) / len(members),
        )
        for name in (*CATEGORIES, "other")
        if (members := by_category.get(name))
    )
    seconds = seconds_budgets(search_config.max_wall_seconds)
    curves = (
        anytime_curve(results, CostMetric.EXPANSIONS, expansion_budgets(search_config.max_expansions)),
        anytime_curve(results, CostMetric.WALL_SECONDS, seconds),
        anytime_curve(results, CostMetric.LEAN_SECONDS, seconds),
    )
    stop_reasons = Counter(result.stop_reason for result in results)
    depths = Counter(len(result.proof_steps) for result in solved)
    multi_step = tuple(
        SolvedProof(result.problem_name, result.proof_steps) for result in solved if len(result.proof_steps) >= 2
    )
    return RunSummary(
        metadata=metadata,
        problems=len(results),
        solved=len(solved),
        solve_rate=len(solved) / len(results),
        categories=categories,
        stop_reasons=tuple(StopReasonCount(reason, count) for reason, count in stop_reasons.most_common()),
        curves=curves,
        costs=(
            cost_table("all", [result.accounting for result in results]),
            cost_table("solved", [result.accounting for result in solved]),
            cost_table("unsolved", [result.accounting for result in results if not result.proved]),
        ),
        steps=step_costs(results),
        proof_depths=tuple(DepthCount(depth, depths[depth]) for depth in sorted(depths)),
        solved_at_depth_two_or_more=len(multi_step),
        multi_step_proofs=multi_step,
        verification_failures=sum(result.verification_failures for result in results),
        start_failures=sum(result.stop_reason == StopReason.START_FAILED for result in results),
    )


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_format_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _format_cell(cell: object) -> str:
    match cell:
        case float():
            return f"{cell:.3g}" if abs(cell) < 1000 else f"{cell:.0f}"
        case _:
            return str(cell).replace("|", "\\|").replace("\n", "<br>")


def render_markdown(summary: RunSummary, title: str) -> str:
    metadata = summary.metadata
    sections = [
        f"# {title}",
        f"Run `{metadata.run_name}` on miniF2F-{metadata.split}, git `{metadata.git_revision}`"
        f"{' (dirty)' if metadata.git_dirty else ''}, config `{metadata.config_file}` (copied as `config.toml`). "
        f"Started {metadata.started_at}, {metadata.run_wall_seconds / 60:.1f} min wall, "
        f"{metadata.cpu_count} CPUs, load average {metadata.load_average_at_start:.1f} at start.",
        f"**Solved {summary.solved}/{summary.problems} ({summary.solve_rate:.1%}).** "
        f"Solved only with proofs of 2 or more steps: {summary.solved_at_depth_two_or_more}. "
        f"Verification failures (bugs): {summary.verification_failures}. "
        f"Statements that failed to start: {summary.start_failures}.",
        "## By category",
        markdown_table(
            ["category", "problems", "solved", "solve rate"],
            [(entry.category, entry.problems, entry.solved, entry.solve_rate) for entry in summary.categories],
        ),
        "## Anytime curves",
        "A theorem counts as solved at budget b if its proof was found after spending at most b in that unit "
        "(per theorem). Wall seconds were measured under the run's concurrency.",
    ]
    for curve in summary.curves:
        sections.append(
            markdown_table(
                [f"{curve.metric} ≤", *(_format_cell(point.budget) for point in curve.points)],
                [
                    ["solved", *(point.solved for point in curve.points)],
                    ["solve rate", *(f"{point.solve_rate:.1%}" for point in curve.points)],
                ],
            )
        )
    sections.append("## Stop reasons")
    sections.append(
        markdown_table(
            ["stop reason", "problems"], [(entry.stop_reason, entry.problems) for entry in summary.stop_reasons]
        )
    )
    sections.append("## Cost per theorem")
    for table in summary.costs:
        if not table.distributions:
            continue
        sections.append(f"{table.group} ({table.problems} theorems):")
        sections.append(
            markdown_table(
                ["quantity", "mean", "median", "p90", "max", "total"],
                [
                    (entry.metric, entry.mean, entry.median, entry.p90, entry.maximum, entry.total)
                    for entry in table.distributions
                ],
            )
        )
    sections.append("## Compute by step")
    sections.append(
        "Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; "
        "closing = the step produced a proof that verified or not; on proof paths = steps of found proofs."
    )
    sections.append(
        markdown_table(
            [
                "step",
                "attempts",
                "Lean s",
                "share",
                "mean s",
                "children",
                "duplicates",
                "failures",
                "errors",
                "heartbeat timeouts",
                "wall-clock timeouts",
                "closing",
                "on proof paths",
            ],
            [
                (
                    cost.step,
                    cost.attempts,
                    cost.lean_seconds,
                    f"{cost.lean_seconds_fraction:.1%}",
                    cost.mean_seconds,
                    cost.children,
                    cost.duplicates,
                    cost.failures,
                    cost.errors,
                    cost.heartbeat_timeouts,
                    cost.wall_clock_timeouts,
                    cost.closing,
                    cost.on_proof_paths,
                )
                for cost in summary.steps
            ],
        )
    )
    sections.append("## Proof depths")
    sections.append(
        markdown_table(["steps", "solved"], [(entry.depth, entry.solved) for entry in summary.proof_depths])
    )
    if summary.multi_step_proofs:
        sections.append("Proofs with 2 or more steps:")
        sections.append(
            markdown_table(
                ["problem", "steps"],
                [(proof.problem_name, " ⟶ ".join(proof.proof_steps)) for proof in summary.multi_step_proofs],
            )
        )
    return "\n\n".join(sections) + "\n"
