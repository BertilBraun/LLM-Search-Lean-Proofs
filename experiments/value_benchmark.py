"""Build the fixed value benchmark from search trees, or score it with the search-time estimates the trees recorded.

    python experiments/value_benchmark.py build --trees runs/<run>/trees --output runs/value_benchmark/benchmark.json.gz
    python experiments/value_benchmark.py recorded --benchmark runs/value_benchmark/benchmark.json.gz \
        --trees runs/<run>/trees --output runs/value_benchmark/recorded_metrics.json

`recorded` reads each benchmark state's h from the tree it came from (the value version that ran the search) and
turns it into a proof probability with `RemainingStepsReadout`. A served value model is compared on the same
benchmark by passing its estimates to `benchmark_metrics`.
"""

import argparse
import dataclasses
import json
from pathlib import Path

from lean_search.search import TreeRecord, read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.value.benchmark import (
    BenchmarkConfig,
    LabelledTree,
    benchmark_composition,
    benchmark_metrics,
    build_benchmark,
    read_benchmark,
    recorded_benchmark_estimates,
    write_benchmark,
)
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--trees", nargs="+", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--max-states-per-tree", type=int, default=BenchmarkConfig.max_states_per_tree)
    build.add_argument("--max-states", type=int, default=BenchmarkConfig.max_states)
    recorded = commands.add_parser("recorded")
    recorded.add_argument("--benchmark", required=True, type=Path)
    recorded.add_argument("--trees", nargs="+", required=True, type=Path)
    recorded.add_argument("--output", type=Path)
    return parser.parse_args()


def read_records(directories: list[Path]) -> list[TreeRecord]:
    return [read_tree(path) for directory in directories for path in sorted(directory.glob("*.json.gz"))]


def labelled_tree(record: TreeRecord, readout: RemainingStepsReadout, config: ValueTargetConfig) -> LabelledTree:
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, readout), readout, config)
    return LabelledTree(record, labels, targets)


def main() -> None:
    arguments = parse_arguments()
    readout = RemainingStepsReadout()
    records = read_records(arguments.trees)
    match arguments.command:
        case "build":
            config = BenchmarkConfig(arguments.max_states_per_tree, arguments.max_states)
            trees = [labelled_tree(record, readout, ValueTargetConfig()) for record in records]
            benchmark = build_benchmark(trees, config)
            write_benchmark(arguments.output, benchmark)
            print(json.dumps(dataclasses.asdict(benchmark_composition(benchmark)), indent=1))
        case "recorded":
            benchmark = read_benchmark(arguments.benchmark)
            by_name = {record.problem_name: record for record in records}
            estimates = recorded_benchmark_estimates(benchmark, by_name, readout)
            metrics = benchmark_metrics(benchmark, estimates, BenchmarkConfig())
            text = json.dumps(dataclasses.asdict(metrics), indent=1)
            print(text)
            if arguments.output is not None:
                arguments.output.parent.mkdir(parents=True, exist_ok=True)
                arguments.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
