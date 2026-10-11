"""Compare a policy search run with the automation-only row 0 and report its GPU and Lean throughput.

    python experiments/phase1_search_report.py --run phase1_fewshot_search_qwen3.5-2b

Reads $LEAN_SEARCH_RUNS/<run>/{results.jsonl,run.json,policy.json,gpu.csv} and the baseline's results.jsonl; writes
summary/comparison.{md,json} next to the run's own summary. gpu.csv is optional: `nvidia-smi --query-gpu=timestamp,
utilization.gpu,memory.used,power.draw --format=csv,noheader,nounits -i 0 -l 5` logged during the run.
"""

import argparse
import dataclasses
import json
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.policy.expander import PolicyStatistics
from lean_search.search import SearchResult, StepSource, read_results
from lean_search.search.records import from_json_object
from lean_search.search.summary import (
    CATEGORIES,
    CostMetric,
    RunMetadata,
    anytime_curve,
    category,
    expansion_budgets,
    markdown_table,
    seconds_budgets,
)

RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
BASELINE_RUN = "phase0_automation_baseline"


@dataclass(frozen=True)
class CategoryComparison:
    category: str
    problems: int
    baseline_solved: int
    solved: int
    newly_solved: int
    lost: int


@dataclass(frozen=True)
class TheoremChange:
    problem_name: str
    proof_steps: tuple[str, ...]
    proof_sources: tuple[StepSource, ...]
    stop_reason: str


@dataclass(frozen=True)
class CurveComparison:
    metric: str
    budgets: tuple[float, ...]
    baseline_solved: tuple[int, ...]
    solved: tuple[int, ...]


@dataclass(frozen=True)
class CostSummary:
    mean_generated_tokens: float
    median_generated_tokens: float
    total_generated_tokens: int
    mean_prompt_tokens: float
    total_prompt_tokens: int
    mean_wall_seconds: float
    median_wall_seconds: float
    mean_lean_seconds: float
    total_lean_seconds: float
    mean_expansions: float
    generated_tokens_per_solve: float


@dataclass(frozen=True)
class GpuUtilization:
    readings: int
    mean_utilization: float
    median_utilization: float
    busy_fraction: float
    mean_power_watts: float
    peak_memory_mib: float


@dataclass(frozen=True)
class Throughput:
    run_wall_seconds: float
    policy_window_seconds: float
    requests: int
    samples: int
    samples_per_second: float
    generated_tokens_per_second: float
    mean_request_seconds: float
    total_request_seconds: float
    total_lean_seconds: float
    candidates_per_request: float
    duplicate_sample_fraction: float
    failed_sample_fraction: float
    prompt_cache_hit_rate: float
    requests_without_candidates: int
    unattributed_generated_tokens: int
    prompts_too_long: int
    gpu: GpuUtilization | None


@dataclass(frozen=True)
class Comparison:
    run: str
    baseline: str
    problems: int
    baseline_solved: int
    solved: int
    solved_with_policy_steps: int
    categories: tuple[CategoryComparison, ...]
    newly_solved: tuple[TheoremChange, ...]
    lost: tuple[TheoremChange, ...]
    curves: tuple[CurveComparison, ...]
    costs: CostSummary
    throughput: Throughput


def change(result: SearchResult) -> TheoremChange:
    return TheoremChange(result.problem_name, result.proof_steps, result.proof_sources, str(result.stop_reason))


def category_comparisons(
    results: dict[str, SearchResult], baseline: dict[str, SearchResult]
) -> tuple[CategoryComparison, ...]:
    comparisons = []
    for name in (*CATEGORIES, "other"):
        members = [problem for problem in results if category(problem) == name]
        if members:
            comparisons.append(
                CategoryComparison(
                    category=name,
                    problems=len(members),
                    baseline_solved=sum(baseline[problem].proved for problem in members),
                    solved=sum(results[problem].proved for problem in members),
                    newly_solved=sum(results[problem].proved and not baseline[problem].proved for problem in members),
                    lost=sum(baseline[problem].proved and not results[problem].proved for problem in members),
                )
            )
    return tuple(comparisons)


def curve_comparison(
    metric: CostMetric, budgets: Sequence[float], results: Sequence[SearchResult], baseline: Sequence[SearchResult]
) -> CurveComparison:
    return CurveComparison(
        str(metric),
        tuple(budgets),
        tuple(point.solved for point in anytime_curve(baseline, metric, budgets).points),
        tuple(point.solved for point in anytime_curve(results, metric, budgets).points),
    )


def cost_summary(results: Sequence[SearchResult]) -> CostSummary:
    accountings = [result.accounting for result in results]
    generated = [accounting.generated_tokens for accounting in accountings]
    wall = [accounting.wall_seconds for accounting in accountings]
    solved = sum(result.proved for result in results)
    return CostSummary(
        mean_generated_tokens=statistics.fmean(generated),
        median_generated_tokens=statistics.median(generated),
        total_generated_tokens=sum(generated),
        mean_prompt_tokens=statistics.fmean(accounting.prompt_tokens for accounting in accountings),
        total_prompt_tokens=sum(accounting.prompt_tokens for accounting in accountings),
        mean_wall_seconds=statistics.fmean(wall),
        median_wall_seconds=statistics.median(wall),
        mean_lean_seconds=statistics.fmean(accounting.lean_seconds for accounting in accountings),
        total_lean_seconds=sum(accounting.lean_seconds for accounting in accountings),
        mean_expansions=statistics.fmean(accounting.expansions for accounting in accountings),
        generated_tokens_per_solve=sum(generated) / max(solved, 1),
    )


def gpu_utilization(path: Path) -> GpuUtilization | None:
    if not path.exists():
        return None
    rows = [line.split(", ") for line in path.read_text(encoding="utf-8").splitlines() if line.count(", ") == 3]
    utilization = [float(row[1]) for row in rows]
    return GpuUtilization(
        readings=len(rows),
        mean_utilization=statistics.fmean(utilization),
        median_utilization=statistics.median(utilization),
        busy_fraction=sum(value >= 90 for value in utilization) / len(utilization),
        mean_power_watts=statistics.fmean(float(row[3]) for row in rows),
        peak_memory_mib=max(float(row[2]) for row in rows),
    )


def throughput(run_directory: Path, results: Sequence[SearchResult]) -> Throughput:
    metadata = from_json_object(RunMetadata, json.loads((run_directory / "run.json").read_text(encoding="utf-8")))
    policy = from_json_object(PolicyStatistics, json.loads((run_directory / "policy.json").read_text(encoding="utf-8")))
    failed_samples = (
        policy.truncated_samples + policy.samples_without_block + policy.empty_samples + policy.forbidden_samples
    )
    return Throughput(
        run_wall_seconds=metadata.run_wall_seconds,
        policy_window_seconds=policy.window_seconds,
        requests=policy.requests,
        samples=policy.samples,
        samples_per_second=policy.samples / policy.window_seconds,
        generated_tokens_per_second=policy.generated_tokens / policy.window_seconds,
        mean_request_seconds=policy.request_seconds / policy.requests,
        total_request_seconds=policy.request_seconds,
        total_lean_seconds=sum(result.accounting.lean_seconds for result in results),
        candidates_per_request=policy.candidates / policy.requests,
        duplicate_sample_fraction=policy.duplicate_samples / policy.samples,
        failed_sample_fraction=failed_samples / policy.samples,
        prompt_cache_hit_rate=policy.cached_prompt_tokens / policy.prompt_tokens,
        requests_without_candidates=policy.requests_without_candidates,
        unattributed_generated_tokens=policy.unattributed_generated_tokens,
        prompts_too_long=policy.prompts_too_long,
        gpu=gpu_utilization(run_directory / "gpu.csv"),
    )


def compare(run: str, baseline_run: str) -> Comparison:
    run_directory = RUNS_DIRECTORY / run
    results = {result.problem_name: result for result in read_results(run_directory / "results.jsonl")}
    baseline_all = {
        result.problem_name: result for result in read_results(RUNS_DIRECTORY / baseline_run / "results.jsonl")
    }
    baseline = {name: baseline_all[name] for name in results}
    max_expansions = max(result.accounting.expansions for result in results.values())
    max_seconds = max(result.accounting.wall_seconds for result in results.values())
    ordered = [results[name] for name in sorted(results)]
    ordered_baseline = [baseline[name] for name in sorted(results)]
    return Comparison(
        run=run,
        baseline=baseline_run,
        problems=len(results),
        baseline_solved=sum(result.proved for result in baseline.values()),
        solved=sum(result.proved for result in results.values()),
        solved_with_policy_steps=sum(
            result.proved and StepSource.POLICY in result.proof_sources for result in results.values()
        ),
        categories=category_comparisons(results, baseline),
        newly_solved=tuple(
            change(results[name]) for name in sorted(results) if results[name].proved and not baseline[name].proved
        ),
        lost=tuple(
            change(results[name]) for name in sorted(results) if baseline[name].proved and not results[name].proved
        ),
        curves=(
            curve_comparison(CostMetric.EXPANSIONS, expansion_budgets(max_expansions), ordered, ordered_baseline),
            curve_comparison(CostMetric.WALL_SECONDS, seconds_budgets(max_seconds), ordered, ordered_baseline),
        ),
        costs=cost_summary(ordered),
        throughput=throughput(run_directory, ordered),
    )


def proof_text(theorem: TheoremChange) -> str:
    return " ⟶ ".join(
        f"[{'P' if source == StepSource.POLICY else 'A'}] {step}"
        for step, source in zip(theorem.proof_steps, theorem.proof_sources, strict=True)
    )


def render(comparison: Comparison) -> str:
    rate = comparison.solved / comparison.problems
    baseline_rate = comparison.baseline_solved / comparison.problems
    costs = comparison.costs
    speed = comparison.throughput
    sections = [
        f"# {comparison.run} vs {comparison.baseline}",
        f"**Solved {comparison.solved}/{comparison.problems} ({rate:.1%}) vs {comparison.baseline_solved}/"
        f"{comparison.problems} ({baseline_rate:.1%}) for row 0**: {len(comparison.newly_solved)} newly solved, "
        f"{len(comparison.lost)} lost. Proofs using at least one policy step: {comparison.solved_with_policy_steps}. "
        "Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.",
        "## By category",
        markdown_table(
            ["category", "problems", "row 0", "this run", "newly solved", "lost"],
            [
                (entry.category, entry.problems, entry.baseline_solved, entry.solved, entry.newly_solved, entry.lost)
                for entry in comparison.categories
            ],
        ),
        "## Anytime curves (solved theorems at budget)",
    ]
    for curve in comparison.curves:
        sections.append(
            markdown_table(
                [f"{curve.metric} ≤", *(f"{budget:g}" for budget in curve.budgets)],
                [["row 0", *curve.baseline_solved], ["this run", *curve.solved]],
            )
        )
    sections += [
        "## Cost per theorem",
        markdown_table(
            ["quantity", "value"],
            [
                (
                    "mean / median generated tokens",
                    f"{costs.mean_generated_tokens:.0f} / {costs.median_generated_tokens:.0f}",
                ),
                ("total generated tokens", f"{costs.total_generated_tokens:,}"),
                ("generated tokens per solved theorem", f"{costs.generated_tokens_per_solve:,.0f}"),
                ("mean prompt tokens (computed once per request)", f"{costs.mean_prompt_tokens:.0f}"),
                ("mean / median wall seconds", f"{costs.mean_wall_seconds:.1f} / {costs.median_wall_seconds:.1f}"),
                ("mean Lean seconds", f"{costs.mean_lean_seconds:.1f}"),
                ("mean expansions", f"{costs.mean_expansions:.1f}"),
            ],
        ),
        "## Throughput in the search",
        markdown_table(
            ["quantity", "value"],
            [
                ("run wall minutes", f"{speed.run_wall_seconds / 60:.1f}"),
                ("policy requests / samples", f"{speed.requests:,} / {speed.samples:,}"),
                ("samples/s over the policy window", f"{speed.samples_per_second:.1f}"),
                ("generated tokens/s", f"{speed.generated_tokens_per_second:.0f}"),
                ("mean request latency s", f"{speed.mean_request_seconds:.2f}"),
                (
                    "summed request s / summed Lean s",
                    f"{speed.total_request_seconds:,.0f} / {speed.total_lean_seconds:,.0f}",
                ),
                ("distinct candidates per request", f"{speed.candidates_per_request:.1f}"),
                (
                    "duplicate / failed sample fraction",
                    f"{speed.duplicate_sample_fraction:.1%} / {speed.failed_sample_fraction:.1%}",
                ),
                ("prompt cache hit rate", f"{speed.prompt_cache_hit_rate:.1%}"),
                (
                    "requests without candidates (unattributed tokens)",
                    f"{speed.requests_without_candidates} ({speed.unattributed_generated_tokens:,})",
                ),
                ("prompts too long", speed.prompts_too_long),
                *(
                    []
                    if speed.gpu is None
                    else [
                        (
                            "GPU utilization mean / median",
                            f"{speed.gpu.mean_utilization:.0f}% / {speed.gpu.median_utilization:.0f}%",
                        ),
                        ("readings at ≥ 90% utilization", f"{speed.gpu.busy_fraction:.0%} of {speed.gpu.readings}"),
                        (
                            "mean power W / peak memory MiB",
                            f"{speed.gpu.mean_power_watts:.0f} / {speed.gpu.peak_memory_mib:.0f}",
                        ),
                    ]
                ),
            ],
        ),
        "## Newly solved (P = policy step, A = automation)",
        "\n".join(f"- `{theorem.problem_name}`: {proof_text(theorem)}" for theorem in comparison.newly_solved)
        or "none",
        "## Lost against row 0",
        "\n".join(f"- `{theorem.problem_name}` ({theorem.stop_reason})" for theorem in comparison.lost) or "none",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--baseline", default=BASELINE_RUN)
    arguments = parser.parse_args()
    comparison = compare(arguments.run, arguments.baseline)
    summary = RUNS_DIRECTORY / arguments.run / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    (summary / "comparison.json").write_text(
        json.dumps(dataclasses.asdict(comparison), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (summary / "comparison.md").write_text(render(comparison), encoding="utf-8")
    print(f"{comparison.solved}/{comparison.problems} vs {comparison.baseline_solved}; report in {summary}")


if __name__ == "__main__":
    main()
