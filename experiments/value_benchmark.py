"""Build the fixed value benchmark from search trees, score it fresh with a served value model, and report metrics.

    python experiments/value_benchmark.py build --trees runs/<run>/trees --output runs/value_benchmark/benchmark.json.gz
    python experiments/value_benchmark.py score --benchmark runs/value_benchmark/benchmark.json.gz \
        --model search-qwen3.5-2b --tokenizer Qwen/Qwen3.5-2B --adapter value-v0 \
        --server-urls http://127.0.0.1:8100/v1 http://127.0.0.1:8101/v1 \
        --output runs/value_benchmark/scores_value-v0.json.gz
    python experiments/value_benchmark.py metrics --benchmark runs/value_benchmark/benchmark.json.gz \
        --scores runs/value_benchmark/scores_*.json.gz --output runs/value_benchmark/metrics.json
    python experiments/value_benchmark.py recorded --benchmark ... --trees runs/<run>/trees
    python experiments/value_benchmark.py looked-up --benchmark ... --trees runs/<v0-guided run>/trees --model value-v0

Each trees directory is a run's `trees/`; the run's `config.toml` next to it (or `--config`) gives the provenance:
value-free (no value model chose the labels), or A* on a named value model. `build` refuses trees guided by a value
model being compared (any value model unless `--compared-models` names them) unless `--guided-trees warn`; the
benchmark should come from a value-free search, e.g. a log-probability best-first run of the starting policy
(experiments/configs/value_benchmark_search.toml).

`score` stores every state's bin distribution read through vLLM as A* reads it, so models are compared on identical
states; `metrics` reads those files. `recorded` reads the h each benchmark tree's own search recorded (ranking and
steps only: an h has no probability, and the labels of a value-guided tree were chosen by that same model);
`looked-up` reads the h a model recorded for identical goals of the same statements in other searches it guided.
"""

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

from lean_search.search import TreeRecord, read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkEstimates,
    BenchmarkMetrics,
    GuidedTrees,
    LabelledTree,
    TreeKey,
    TreeSource,
    ValueBenchmark,
    benchmark_composition,
    benchmark_metrics,
    build_benchmark,
    conflict_message,
    fresh_estimates,
    guidance_conflicts,
    looked_up_estimates,
    read_benchmark,
    read_scores,
    recorded_benchmark_estimates,
    search_provenance,
    write_benchmark,
    write_scores,
)
from lean_search.value.benchmark_scoring import score_benchmark
from lean_search.value.bins import Readout
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import open_value_estimator
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--trees", nargs="+", required=True, type=Path)
    build.add_argument("--config", type=Path, help="the run config for trees directories without config.toml beside")
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--max-states-per-tree", type=int, default=BenchmarkConfig.max_states_per_tree)
    build.add_argument("--max-states", type=int, default=BenchmarkConfig.max_states)
    build.add_argument("--compared-models", nargs="+", help="served value model names; default: every value model")
    build.add_argument("--guided-trees", type=GuidedTrees, choices=list(GuidedTrees), default=GuidedTrees.REFUSE)
    score = commands.add_parser("score")
    score.add_argument("--benchmark", required=True, type=Path)
    score.add_argument("--model", required=True)
    score.add_argument("--tokenizer", required=True)
    score.add_argument("--adapter", help="the served value adapter; omit for a merged value model")
    score.add_argument("--server-urls", nargs="+", required=True)
    score.add_argument("--output", required=True, type=Path)
    metrics = commands.add_parser("metrics")
    metrics.add_argument("--benchmark", required=True, type=Path)
    metrics.add_argument("--scores", nargs="+", required=True, type=Path)
    metrics.add_argument("--guided-trees", type=GuidedTrees, choices=list(GuidedTrees), default=GuidedTrees.REFUSE)
    metrics.add_argument("--eight-or-more-steps", type=float, default=Readout.eight_or_more_steps)
    metrics.add_argument("--output", type=Path)
    recorded = commands.add_parser("recorded")
    recorded.add_argument("--benchmark", required=True, type=Path)
    recorded.add_argument("--trees", nargs="+", required=True, type=Path)
    recorded.add_argument("--output", type=Path)
    looked_up = commands.add_parser("looked-up")
    looked_up.add_argument("--benchmark", required=True, type=Path)
    looked_up.add_argument("--trees", nargs="+", required=True, type=Path)
    looked_up.add_argument("--model", required=True, help="the value model that guided those trees")
    looked_up.add_argument("--output", type=Path)
    return parser.parse_args()


def run_name(trees: Path) -> str:
    return trees.resolve().parent.name


def read_records(directory: Path) -> list[TreeRecord]:
    return [read_tree(path) for path in sorted(directory.glob("*.json.gz"))]


def labelled_tree(record: TreeRecord, readout: RemainingStepsReadout, config: ValueTargetConfig) -> LabelledTree:
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, readout), readout, config)
    return LabelledTree(record, labels, targets)


def tree_source(directory: Path, fallback_config: Path | None) -> TreeSource:
    records = read_records(directory)
    config = directory.resolve().parent / "config.toml"
    if not config.exists():
        config = fallback_config
    text = None if config is None else config.read_text(encoding="utf-8")
    provenance = search_provenance(run_name(directory), text, records)
    readout = RemainingStepsReadout()
    return TreeSource(provenance, tuple(labelled_tree(record, readout, ValueTargetConfig()) for record in records))


def refuse_or_warn(messages: tuple[str, ...], action: GuidedTrees) -> None:
    if not messages:
        return
    text = "\n".join(f"  {message}" for message in messages)
    match action:
        case GuidedTrees.REFUSE:
            raise SystemExit(f"Labels selected by a compared value model (--guided-trees warn to go on):\n{text}")
        case GuidedTrees.WARN:
            print(f"Warning: labels selected by a compared value model:\n{text}", file=sys.stderr)


def build(arguments: argparse.Namespace) -> None:
    config = BenchmarkConfig(arguments.max_states_per_tree, arguments.max_states)
    sources = [tree_source(directory, arguments.config) for directory in arguments.trees]
    for source in sources:
        print(json.dumps(dataclasses.asdict(source.provenance)))
    conflicts = guidance_conflicts([source.provenance for source in sources], arguments.compared_models)
    refuse_or_warn(tuple(conflict_message(source) for source in conflicts), arguments.guided_trees)
    benchmark = build_benchmark(sources, config)
    write_benchmark(arguments.output, benchmark)
    print(json.dumps(dataclasses.asdict(benchmark_composition(benchmark, config)), indent=1))


async def score(arguments: argparse.Namespace) -> None:
    benchmark = read_benchmark(arguments.benchmark)
    config = ValueConfig(
        model=arguments.model,
        tokenizer=arguments.tokenizer,
        server_urls=tuple(arguments.server_urls),
        adapter=arguments.adapter,
    )
    async with open_value_estimator(config) as estimator:
        scores = await score_benchmark(estimator, benchmark)
        print(json.dumps(dataclasses.asdict(estimator.statistics)))
    write_scores(arguments.output, scores)
    missing = sum(distribution is None for distribution in scores.distributions)
    print(f"{len(scores.distributions) - missing} states scored by {scores.model}, {missing} too long")


def optional(value: float | None) -> str:
    return "–" if value is None else f"{value:.3f}"


def summary_lines(metrics: BenchmarkMetrics) -> list[str]:
    ranking = metrics.ranking
    lines = [
        f"{metrics.estimates}",
        f"  states {metrics.states}, without estimate {metrics.states_without_estimate}, groups {metrics.groups}",
        f"  circular runs (labels chosen by this model): {', '.join(metrics.circular_runs) or 'none'}",
        f"  proof over labelled siblings: {optional(ranking.pairwise_accuracy)} ({ranking.pairs} pairs); "
        f"top {optional(ranking.top_accuracy)} ({ranking.groups_with_proof_state} groups with a proof state)",
    ]
    for name, pairs in (
        ("proof over dead end", ranking.proof_over_dead_end),
        ("proof over expanded", ranking.proof_over_expanded),
        ("expanded over dead end", ranking.expanded_over_dead_end),
    ):
        lines.append(f"    {name}: {optional(pairs.accuracy)} ({pairs.pairs} pairs)")
    lines.append(
        f"  excluded siblings: {ranking.never_expanded_siblings} never expanded, "
        f"{ranking.unexplored_expanded_siblings} expanded without an explored subtree"
    )
    steps = metrics.steps
    lines.append(
        f"  steps on {steps.proof_graph_states} proof-graph states: MAE {optional(steps.mean_absolute_error)}, "
        f"Spearman {optional(steps.spearman)}"
    )
    if metrics.calibration is not None and metrics.separation is not None:
        lines.append(
            f"  anchors: ECE {optional(metrics.calibration.anchor_expected_calibration_error)}, "
            f"Brier {optional(metrics.calibration.anchor_brier_score)} ({metrics.calibration.anchor_states} states); "
            f"AUC proof/dead {optional(metrics.separation.proof_graph_over_dead_end_auc)}, "
            f"expanded/dead {optional(metrics.separation.expanded_over_dead_end_auc)}"
        )
    return lines


def report(benchmark: ValueBenchmark, estimates: list[BenchmarkEstimates], output: Path | None) -> None:
    metrics = [benchmark_metrics(benchmark, estimate, BenchmarkConfig()) for estimate in estimates]
    for entry in metrics:
        print("\n".join(summary_lines(entry)))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps([dataclasses.asdict(entry) for entry in metrics], indent=1, ensure_ascii=False)
        output.write_text(text, encoding="utf-8")


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "build":
            build(arguments)
        case "score":
            asyncio.run(score(arguments))
        case "metrics":
            benchmark = read_benchmark(arguments.benchmark)
            scores = [read_scores(path) for path in arguments.scores]
            conflicts = guidance_conflicts(benchmark.provenance, [entry.model for entry in scores])
            refuse_or_warn(tuple(conflict_message(source) for source in conflicts), arguments.guided_trees)
            readout = Readout(eight_or_more_steps=arguments.eight_or_more_steps)
            report(benchmark, [fresh_estimates(benchmark, entry, readout) for entry in scores], arguments.output)
        case "recorded":
            benchmark = read_benchmark(arguments.benchmark)
            records = {
                TreeKey(run_name(directory), record.problem_name): record
                for directory in arguments.trees
                for record in read_records(directory)
            }
            report(benchmark, [recorded_benchmark_estimates(benchmark, records)], arguments.output)
        case "looked-up":
            benchmark = read_benchmark(arguments.benchmark)
            records = [record for directory in arguments.trees for record in read_records(directory)]
            report(benchmark, [looked_up_estimates(benchmark, records, arguments.model)], arguments.output)


if __name__ == "__main__":
    main()
