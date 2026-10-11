"""Label search trees for statistics only: exact, censored and dead nodes, and their depths.

    python experiments/phase3_tree_labels.py --run-name phase3_tree_labels_row1 \
        --runs phase1_fewshot_search_qwen3.5-2b phase1_fewshot_search_qwen3.5-2b-base phase0_automation_baseline

Reads $LEAN_SEARCH_RUNS/<run>/trees/*.json.gz and writes only $LEAN_SEARCH_RUNS/<run-name>/summary/
{summary.json,README.md}. The miniF2F trees exercise the labeler; they never become training data.
"""

import argparse
import dataclasses
import json
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.search import NodeStatus, TreeRecord, read_tree
from lean_search.search.summary import markdown_table
from lean_search.value.bins import STEP_BIN_COUNT
from lean_search.value.labels import (
    LabelCounts,
    LabelKind,
    TreeLabelConfig,
    ValueExample,
    label_counts,
    merge_duplicates,
    tree_examples,
)

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
DEPTH_BUCKETS = 17


@dataclass(frozen=True)
class DepthHistograms:
    # Labelled nodes per depth 0..15 and 16+.
    exact: tuple[int, ...]
    at_least: tuple[int, ...]
    dead: tuple[int, ...]


@dataclass(frozen=True)
class RunLabelStatistics:
    run: str
    trees: int
    solved_trees: int
    nodes: int
    nodes_without_goals: int
    statuses: dict[str, int]
    labels: LabelCounts
    # Exact labels of nodes off the found path, which reach the proof through duplicate edges.
    exact_off_path: int
    # Failed nodes kept censored because an attempt below them was lost to an infrastructure failure.
    failed_but_censored: int
    trees_with_dead: int
    unsolved_trees_with_dead_root: int
    distinct_states: int
    depths: DepthHistograms


@dataclass(frozen=True)
class TreeLabelSummary:
    config: TreeLabelConfig
    runs: tuple[RunLabelStatistics, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    return parser.parse_args()


def depth_histogram(examples: Sequence[ValueExample], kind: LabelKind) -> tuple[int, ...]:
    counts = [0] * DEPTH_BUCKETS
    for example in examples:
        if example.kind == kind:
            counts[min(example.depth, DEPTH_BUCKETS - 1)] += 1
    return tuple(counts)


def run_statistics(run: str, records: Sequence[TreeRecord], config: TreeLabelConfig) -> RunLabelStatistics:
    examples: list[ValueExample] = []
    exact_off_path = 0
    failed_but_censored = 0
    trees_with_dead = 0
    unsolved_trees_with_dead_root = 0
    statuses: Counter[str] = Counter()
    for record in records:
        tree_labels = tree_examples(record, run, config)
        examples.extend(tree_labels)
        labelled_nodes = [node for node in record.nodes if node.goals]
        for node, example in zip(labelled_nodes, tree_labels, strict=True):
            exact_off_path += example.kind == LabelKind.EXACT and node.status != NodeStatus.PROVED
            failed_but_censored += example.kind == LabelKind.AT_LEAST and node.status == NodeStatus.FAILED
        trees_with_dead += any(example.kind == LabelKind.DEAD for example in tree_labels)
        root_label = tree_labels[0]
        unsolved_trees_with_dead_root += not record.result.proved and root_label.kind == LabelKind.DEAD
        statuses.update(str(node.status) for node in record.nodes)
    return RunLabelStatistics(
        run=run,
        trees=len(records),
        solved_trees=sum(record.result.proved for record in records),
        nodes=sum(len(record.nodes) for record in records),
        nodes_without_goals=sum(not node.goals for record in records for node in record.nodes),
        statuses=dict(sorted(statuses.items())),
        labels=label_counts(examples),
        exact_off_path=exact_off_path,
        failed_but_censored=failed_but_censored,
        trees_with_dead=trees_with_dead,
        unsolved_trees_with_dead_root=unsolved_trees_with_dead_root,
        distinct_states=len(merge_duplicates(examples)),
        depths=DepthHistograms(
            exact=depth_histogram(examples, LabelKind.EXACT),
            at_least=depth_histogram(examples, LabelKind.AT_LEAST),
            dead=depth_histogram(examples, LabelKind.DEAD),
        ),
    )


def percent(count: int, total: int) -> str:
    return f"{count:,} ({count / total:.1%})" if total else "0"


def render_markdown(summary: TreeLabelSummary) -> str:
    overview = [
        [
            statistics.run,
            f"{statistics.solved_trees}/{statistics.trees}",
            f"{statistics.labels.examples:,}",
            percent(statistics.labels.exact, statistics.labels.examples),
            percent(statistics.labels.at_least, statistics.labels.examples),
            percent(statistics.labels.dead, statistics.labels.examples),
            statistics.exact_off_path,
            statistics.failed_but_censored,
            statistics.trees_with_dead,
            statistics.unsolved_trees_with_dead_root,
            f"{statistics.distinct_states:,}",
        ]
        for statistics in summary.runs
    ]
    bin_names = [str(steps) for steps in range(1, STEP_BIN_COUNT)] + [f"{STEP_BIN_COUNT}+"]
    bins = [
        [statistics.run, kind, *counts]
        for statistics in summary.runs
        for kind, counts in (
            ("exact", statistics.labels.exact_bins),
            ("at least", statistics.labels.at_least_bins),
        )
    ]
    depth_names = [str(depth) for depth in range(DEPTH_BUCKETS - 1)] + [f"{DEPTH_BUCKETS - 1}+"]
    depths = [
        [statistics.run, kind, *counts]
        for statistics in summary.runs
        for kind, counts in (
            ("exact", statistics.depths.exact),
            ("at least", statistics.depths.at_least),
            ("dead", statistics.depths.dead),
        )
    ]
    status_names = sorted({status for statistics in summary.runs for status in statistics.statuses})
    statuses = [
        [
            statistics.run,
            statistics.nodes,
            statistics.nodes_without_goals,
            *(statistics.statuses.get(status, 0) for status in status_names),
        ]
        for statistics in summary.runs
    ]
    config = summary.config
    sections = [
        "# Value labels of search trees (statistics only)",
        "miniF2F-valid trees exercise the tree labeler; they are never value training data. Every node with goals "
        "gets one label: **exact** remaining steps when it reaches the verified proof (fewest edges over child and "
        "duplicate edges), else **at least** 1 + the fewest edges to a frontier node (open, i.e. not fully expanded, "
        "or with an attempt lost to an infrastructure failure) when it reaches one, else **dead** (everything below "
        f"it was expanded without a proof). Weights: exact 1, at least {config.at_least_weight:g}, dead "
        f"{config.dead_weight:g}. Proved states (no goals) get no label.",
        markdown_table(
            [
                "Run",
                "Solved trees",
                "Labelled nodes",
                "Exact",
                "At least",
                "Dead",
                "Exact off the found path",
                "Failed but censored",
                "Trees with a dead node",
                "Unsolved trees with a dead root",
                "Distinct states",
            ],
            overview,
        ),
        "## Remaining steps (exact) and lower bounds (at least)",
        markdown_table(["Run", "Label", *bin_names], bins),
        "## Depth of labelled nodes",
        markdown_table(["Run", "Label", *depth_names], depths),
        "## Node statuses",
        markdown_table(["Run", "Nodes", "Without goals", *status_names], statuses),
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    config = TreeLabelConfig()
    runs = []
    for run in arguments.runs:
        records = [read_tree(path) for path in sorted((RUNS_DIRECTORY / run / "trees").glob("*.json.gz"))]
        runs.append(run_statistics(run, records, config))
        print(f"{run}: {len(records)} trees", flush=True)
    summary = TreeLabelSummary(config, tuple(runs))
    summary_directory = RUNS_DIRECTORY / arguments.run_name / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
