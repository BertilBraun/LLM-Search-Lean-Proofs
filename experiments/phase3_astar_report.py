"""Compare search runs on their shared problems: solve rates, anytime curves, changes, value calibration on the trees.

    python experiments/phase3_astar_report.py --run-name phase3_astar_v0 \
        --runs phase0_automation_baseline phase1_fewshot_search_qwen3.5-2b phase2_sft_v1_search phase3_astar_v0 \
        --references phase0_automation_baseline phase1_fewshot_search_qwen3.5-2b phase2_sft_v1_search

Every run is compared on the problems all of them ran, so a run on a subset restricts the comparison to that subset.
Calibration relates each tree node's value estimate h (A* runs only) to its label from the tree labeler: exact
remaining steps for nodes that reach the proof, dead for fully expanded nodes without a proof, at least n for the
rest. miniF2F trees are only evaluated here, never trained on. Writes $LEAN_SEARCH_RUNS/<run-name>/summary/
{report.json,README.md}.
"""

import argparse
import dataclasses
import json
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.search import PriorityKind, SearchResult, load_run_config, read_results, read_tree
from lean_search.search.summary import (
    CATEGORIES,
    CostMetric,
    anytime_curve,
    category,
    expansion_budgets,
    markdown_table,
    seconds_budgets,
)
from lean_search.value.labels import LABEL_GROUPS, LabelKind, TreeLabelConfig, label_group, tree_examples
from lean_search.value.metrics import roc_auc, spearman_correlation

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
GENERATION_BUDGETS = (16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0)
TOKEN_BUDGETS = (500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0, 50000.0, 100000.0, 200000.0)


@dataclass(frozen=True)
class RunSettings:
    run: str
    priority: str
    value_weight: float | None
    dead_steps: float | None
    depth_weight: float | None
    policy_prior_weight: float | None
    # Policy samples per expansion; 0 without a policy.
    samples: int


@dataclass(frozen=True)
class RunOutcome:
    settings: RunSettings
    solved: int
    solve_rate: float
    mean_expansions: float
    mean_generated_tokens: float
    mean_value_prompt_tokens: float
    mean_wall_seconds: float
    mean_lean_seconds: float
    generated_tokens_per_solve: float
    solved_by_category: tuple[int, ...]


@dataclass(frozen=True)
class Curve:
    metric: str
    budgets: tuple[float, ...]
    # Aligned with the report's runs.
    solved: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class Changes:
    run: str
    reference: str
    newly_solved: tuple[str, ...]
    lost: tuple[str, ...]


@dataclass(frozen=True)
class LabelCalibration:
    label: str
    nodes: int
    mean_h: float
    p10_h: float
    median_h: float
    p90_h: float


@dataclass(frozen=True)
class Calibration:
    run: str
    nodes_with_estimates: int
    by_label: tuple[LabelCalibration, ...]
    # Exact nodes: rank correlation of h with the remaining steps.
    spearman_exact: float | None
    # h separating dead nodes (positive) from exact nodes.
    dead_auc: float | None
    mean_root_h_solved: float | None
    mean_root_h_unsolved: float | None


@dataclass(frozen=True)
class SearchReport:
    problems: int
    categories: tuple[str, ...]
    category_sizes: tuple[int, ...]
    runs: tuple[RunOutcome, ...]
    curves: tuple[Curve, ...]
    changes: tuple[Changes, ...]
    calibrations: tuple[Calibration, ...]


@dataclass(frozen=True)
class LabelledEstimate:
    label: str
    kind: LabelKind
    steps: int
    h: float


@dataclass(frozen=True)
class TreeEstimates:
    nodes: list[LabelledEstimate]
    solved_roots: list[float]
    unsolved_roots: list[float]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--references", nargs="*", default=[])
    return parser.parse_args()


def run_settings(run: str) -> RunSettings:
    config = load_run_config(RUNS_DIRECTORY / run / "config.toml")
    is_a_star = config.priority.kind == PriorityKind.A_STAR
    return RunSettings(
        run=run,
        priority=str(config.priority.kind),
        value_weight=config.priority.value_weight if is_a_star else None,
        dead_steps=config.value.readout.dead_steps if is_a_star and config.value.model else None,
        depth_weight=config.priority.depth_weight if is_a_star else None,
        policy_prior_weight=config.priority.policy_prior_weight if is_a_star else None,
        samples=config.policy.sample_count if config.expander.kind.uses_policy else 0,
    )


def outcome(settings: RunSettings, results: Sequence[SearchResult], categories: Sequence[str]) -> RunOutcome:
    accountings = [result.accounting for result in results]
    solved = sum(result.proved for result in results)
    generated = sum(accounting.generated_tokens for accounting in accountings)
    return RunOutcome(
        settings=settings,
        solved=solved,
        solve_rate=solved / len(results),
        mean_expansions=statistics.fmean(accounting.expansions for accounting in accountings),
        mean_generated_tokens=generated / len(results),
        mean_value_prompt_tokens=statistics.fmean(accounting.value_prompt_tokens for accounting in accountings),
        mean_wall_seconds=statistics.fmean(accounting.wall_seconds for accounting in accountings),
        mean_lean_seconds=statistics.fmean(accounting.lean_seconds for accounting in accountings),
        generated_tokens_per_solve=generated / max(solved, 1),
        solved_by_category=tuple(
            sum(result.proved for result in results if category(result.problem_name) == name) for name in categories
        ),
    )


def curve(metric: CostMetric, budgets: Sequence[float], runs: Sequence[Sequence[SearchResult]]) -> Curve:
    return Curve(
        str(metric),
        tuple(budgets),
        tuple(tuple(point.solved for point in anytime_curve(results, metric, budgets).points) for results in runs),
    )


def generations_curve(
    budgets: Sequence[float], runs: Sequence[Sequence[SearchResult]], settings: Sequence[RunSettings]
) -> Curve:
    """Policy samples spent when the proof was found: expansions times samples per expansion."""
    solved = []
    for results, run_setting in zip(runs, settings, strict=True):
        costs = [result.solved_at.expansions * run_setting.samples for result in results if result.solved_at]
        solved.append(tuple(sum(cost <= budget for cost in costs) for budget in budgets))
    return Curve("policy_generations", tuple(budgets), tuple(solved))


def changes(run: str, reference: str, results: Sequence[SearchResult], baseline: Sequence[SearchResult]) -> Changes:
    pairs = list(zip(results, baseline, strict=True))
    return Changes(
        run=run,
        reference=reference,
        newly_solved=tuple(result.problem_name for result, other in pairs if result.proved and not other.proved),
        lost=tuple(result.problem_name for result, other in pairs if other.proved and not result.proved),
    )


def tree_estimates(run: str, problems: Sequence[str]) -> TreeEstimates:
    estimates = TreeEstimates([], [], [])
    for problem in problems:
        path = RUNS_DIRECTORY / run / "trees" / f"{problem}.json.gz"
        if not path.exists():
            continue
        record = read_tree(path)
        labelled_nodes = [node for node in record.nodes if node.goals]
        examples = tree_examples(record, run, TreeLabelConfig())
        for node, example in zip(labelled_nodes, examples, strict=True):
            if node.value_estimate is not None:
                estimates.nodes.append(
                    LabelledEstimate(label_group(example), example.kind, example.steps, node.value_estimate)
                )
        root_h = record.nodes[0].value_estimate
        if root_h is not None:
            (estimates.solved_roots if record.result.proved else estimates.unsolved_roots).append(root_h)
    return estimates


def quantile(ordered: Sequence[float], fraction: float) -> float:
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def calibration(run: str, problems: Sequence[str]) -> Calibration:
    trees = tree_estimates(run, problems)
    estimates = trees.nodes
    by_label = []
    for label in LABEL_GROUPS:
        values = sorted(estimate.h for estimate in estimates if estimate.label == label)
        if values:
            by_label.append(
                LabelCalibration(
                    label,
                    len(values),
                    statistics.fmean(values),
                    quantile(values, 0.1),
                    quantile(values, 0.5),
                    quantile(values, 0.9),
                )
            )
    exact = [estimate for estimate in estimates if estimate.kind == LabelKind.EXACT]
    exact_h = [estimate.h for estimate in exact]
    exact_steps = [float(estimate.steps) for estimate in exact]
    known = [estimate for estimate in estimates if estimate.kind != LabelKind.AT_LEAST]
    return Calibration(
        run=run,
        nodes_with_estimates=len(estimates),
        by_label=tuple(by_label),
        spearman_exact=spearman_correlation(exact_h, exact_steps) if len(exact) > 1 else None,
        dead_auc=roc_auc([estimate.h for estimate in known], [estimate.kind == LabelKind.DEAD for estimate in known]),
        mean_root_h_solved=statistics.fmean(trees.solved_roots) if trees.solved_roots else None,
        mean_root_h_unsolved=statistics.fmean(trees.unsolved_roots) if trees.unsolved_roots else None,
    )


def build_report(runs: Sequence[str], references: Sequence[str]) -> SearchReport:
    results_by_run = {
        run: {result.problem_name: result for result in read_results(RUNS_DIRECTORY / run / "results.jsonl")}
        for run in runs
    }
    problems = sorted(set.intersection(*(set(results) for results in results_by_run.values())))
    ordered = {run: [results_by_run[run][problem] for problem in problems] for run in runs}
    settings = {run: run_settings(run) for run in runs}
    categories = tuple(name for name in (*CATEGORIES, "other") if any(category(p) == name for p in problems))
    max_expansions = max(result.accounting.expansions for results in ordered.values() for result in results)
    max_seconds = max(result.accounting.wall_seconds for results in ordered.values() for result in results)
    max_tokens = max(result.accounting.generated_tokens for results in ordered.values() for result in results)
    token_budgets = (*(budget for budget in TOKEN_BUDGETS if budget < max_tokens), float(max_tokens))
    runs_in_order = [ordered[run] for run in runs]
    return SearchReport(
        problems=len(problems),
        categories=categories,
        category_sizes=tuple(sum(category(problem) == name for problem in problems) for name in categories),
        runs=tuple(outcome(settings[run], ordered[run], categories) for run in runs),
        curves=(
            curve(CostMetric.EXPANSIONS, expansion_budgets(max_expansions), runs_in_order),
            generations_curve(GENERATION_BUDGETS, runs_in_order, [settings[run] for run in runs]),
            curve(CostMetric.GENERATED_TOKENS, token_budgets, runs_in_order),
            curve(CostMetric.WALL_SECONDS, seconds_budgets(max_seconds), runs_in_order),
        ),
        changes=tuple(
            changes(run, reference, ordered[run], ordered[reference])
            for run in runs
            if run not in references
            for reference in references
        ),
        calibrations=tuple(calibration(run, problems) for run in runs if settings[run].dead_steps is not None),
    )


def optional(value: float | None, format_specification: str) -> str:
    return "–" if value is None else format(value, format_specification)


def render(report: SearchReport) -> str:
    settings_rows = [
        [
            run.settings.run,
            run.settings.priority,
            run.settings.samples,
            optional(run.settings.value_weight, "g"),
            optional(run.settings.depth_weight, "g"),
            optional(run.settings.policy_prior_weight, "g"),
            optional(run.settings.dead_steps, "g"),
            f"{run.solved}/{report.problems} ({run.solve_rate:.1%})",
            f"{run.mean_expansions:.1f}",
            f"{run.mean_generated_tokens:,.0f}",
            f"{run.generated_tokens_per_solve:,.0f}",
            f"{run.mean_value_prompt_tokens:,.0f}",
            f"{run.mean_wall_seconds:.0f}",
            f"{run.mean_lean_seconds:.0f}",
        ]
        for run in report.runs
    ]
    sections = [
        "# Search comparison",
        f"{report.problems} miniF2F-valid problems shared by every run. n is the policy's samples per expansion, λ "
        "A*'s value weight, w_p its policy-prior weight, D the dead-end readout; costs are means per theorem. Value "
        "prompt tokens are the value model's prefill-only requests; policy generations are expansions × n.",
        markdown_table(
            [
                "Run",
                "Priority",
                "n",
                "λ",
                "Depth weight",
                "w_p",
                "D",
                "Solved",
                "Expansions",
                "Generated tokens",
                "Generated tokens per solve",
                "Value prompt tokens",
                "Wall s",
                "Lean s",
            ],
            settings_rows,
        ),
        "## By category",
        markdown_table(
            ["Run", *(f"{name} ({size})" for name, size in zip(report.categories, report.category_sizes, strict=True))],
            [[run.settings.run, *run.solved_by_category] for run in report.runs],
        ),
        "## Anytime curves (solved theorems at budget, per theorem)",
    ]
    for anytime in report.curves:
        sections.append(
            markdown_table(
                [f"{anytime.metric} ≤", *(f"{budget:g}" for budget in anytime.budgets)],
                [[run.settings.run, *solved] for run, solved in zip(report.runs, anytime.solved, strict=True)],
            )
        )
    sections.append("## Newly solved and lost against the reference runs")
    for change in report.changes:
        sections.append(
            f"**{change.run} vs {change.reference}**: {len(change.newly_solved)} newly solved, {len(change.lost)} "
            f"lost.\n\n- newly solved: {', '.join(f'`{name}`' for name in change.newly_solved) or 'none'}\n"
            f"- lost: {', '.join(f'`{name}`' for name in change.lost) or 'none'}"
        )
    if report.calibrations:
        sections += [
            "## Value calibration on the search trees",
            "Each node's h (as scored when it was enqueued) against its label from the tree labeler: exact remaining "
            "steps for nodes that reach the proof (fewest edges), dead for fully expanded nodes without a proof, "
            "at least n otherwise (open nodes: at least 1). Dead AUC: h separating dead from exact nodes.",
        ]
        for calibrated in report.calibrations:
            sections += [
                f"### {calibrated.run}",
                f"{calibrated.nodes_with_estimates:,} labelled nodes with an estimate. Spearman of h with the exact "
                f"remaining steps {optional(calibrated.spearman_exact, '.3f')}; dead AUC "
                f"{optional(calibrated.dead_auc, '.3f')}; mean root h {optional(calibrated.mean_root_h_solved, '.2f')} "
                f"(solved) vs {optional(calibrated.mean_root_h_unsolved, '.2f')} (unsolved).",
                markdown_table(
                    ["Label", "Nodes", "Mean h", "p10", "Median", "p90"],
                    [
                        [
                            entry.label,
                            entry.nodes,
                            f"{entry.mean_h:.2f}",
                            f"{entry.p10_h:.2f}",
                            f"{entry.median_h:.2f}",
                            f"{entry.p90_h:.2f}",
                        ]
                        for entry in calibrated.by_label
                    ],
                ),
            ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    report = build_report(arguments.runs, arguments.references)
    summary = RUNS_DIRECTORY / arguments.run_name / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    (summary / "report.json").write_text(
        json.dumps(dataclasses.asdict(report), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render(report)
    (summary / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
