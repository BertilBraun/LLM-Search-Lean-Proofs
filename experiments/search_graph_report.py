"""Label recorded search trees as graphs and report edge kinds, the proof graph, value targets and GRPO groups.

    python experiments/search_graph_report.py --trees runs/phase5_expansions_visible_student/trees \
        --output runs/search_graph_report_visible_student

Reads <directory>/*.json.gz for each --trees directory; with --output writes summary.json (run totals and per-tree
statistics) and README.md there. Search-time value estimates come from each node's recorded h.
"""

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from lean_search.rl.grpo_groups import RewardConfig, RewardMode, policy_groups
from lean_search.rl.tree_statistics import GraphStatistics, TreeStatistics, graph_statistics, total_statistics
from lean_search.search import read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.search.summary import markdown_table
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets


@dataclass(frozen=True)
class RunReport:
    directory: str
    total: GraphStatistics
    trees: tuple[TreeStatistics, ...]


@dataclass(frozen=True)
class GraphReport:
    readout: RemainingStepsReadout
    targets: ValueTargetConfig
    rewards: RewardConfig
    runs: tuple[RunReport, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", nargs="+", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def run_report(
    directory: Path, readout: RemainingStepsReadout, target_config: ValueTargetConfig, reward_config: RewardConfig
) -> RunReport:
    outcome_config = dataclasses.replace(reward_config, mode=RewardMode.OUTCOME_ONLY)
    trees = []
    for path in sorted(directory.glob("*.json.gz")):
        record = read_tree(path)
        labels = label_graph(record)
        estimates = recorded_estimates(record, readout)
        targets = value_targets(record, labels, estimates, readout, target_config)
        groups = policy_groups(record, labels, estimates, targets, reward_config)
        outcome_groups = policy_groups(record, labels, estimates, targets, outcome_config)
        statistics = graph_statistics(record, labels, targets, groups, outcome_groups, reward_config)
        trees.append(TreeStatistics(record.problem_name, statistics))
    return RunReport(str(directory), total_statistics([tree.statistics for tree in trees]), tuple(trees))


def share(count: float, total: float) -> str:
    return f"{count:,.0f} ({count / total:.1%})" if total else "0"


def render_run(run: RunReport) -> str:
    total = run.total
    edges = total.edges
    failed = (
        edges.lean_error
        + edges.heartbeat_timeout
        + edges.wall_clock_timeout
        + edges.forbidden
        + edges.infrastructure_failure
        + edges.unverified_proof
    )
    duplicates = edges.no_progress + edges.back_to_ancestor + edges.sibling_state + edges.transposition
    kinds = [[field.name, share(getattr(edges, field.name), edges.total)] for field in dataclasses.fields(edges)]
    sizes = ["1", "2-3", "4-7", "8-15", "16-31", "32+"]
    sections = [
        f"## {run.directory}",
        markdown_table(
            ["Trees", "Solved", "Nodes", "Expanded", "Never expanded", "Edges"],
            [
                [
                    total.trees,
                    total.solved_trees,
                    f"{total.nodes:,}",
                    f"{total.expanded_nodes:,}",
                    f"{total.never_expanded_nodes:,}",
                    f"{edges.total:,}",
                ]
            ],
        ),
        markdown_table(
            ["Failed", "New state", "Existing state", "Repeat"],
            [
                [
                    share(failed, edges.total),
                    share(edges.new_state, edges.total),
                    share(duplicates, edges.total),
                    share(edges.repeat, edges.total),
                ]
            ],
        ),
        markdown_table(
            ["No progress", "Back to an ancestor", "Sibling state", "Transposition"],
            [
                [
                    share(edges.no_progress, duplicates),
                    share(edges.back_to_ancestor, duplicates),
                    share(edges.sibling_state, duplicates),
                    share(edges.transposition, duplicates),
                ]
            ],
        ),
        markdown_table(["Edge kind", "Edges"], kinds),
        markdown_table(
            ["Partial failures", "Repeats of a failed sweep tactic", "Forced"],
            [[total.partial_failures, total.repeats_of_failed_automation, total.forced_edges]],
        ),
        markdown_table(
            [
                "Proof path nodes",
                "Proof graph nodes",
                "Off-path proof graph nodes",
                "Transpositions into the proof graph",
                "from off-path nodes",
                "off-path source nodes",
                "into the found path",
                "Dead ends",
                "Expanded off graph",
            ],
            [
                [
                    total.proof_path_nodes,
                    total.proof_graph_nodes,
                    total.off_path_proof_graph_nodes,
                    total.transpositions_into_proof_graph,
                    total.off_path_transpositions_into_proof_graph,
                    total.off_path_transposition_sources,
                    total.off_path_transpositions_into_proof_path,
                    total.dead_ends,
                    total.expanded_off_graph_nodes,
                ]
            ],
        ),
        markdown_table(
            ["Proof graph targets", "Dead-end targets", "Averaged targets", "Expanded without target"],
            [
                [
                    total.proof_graph_targets,
                    total.dead_end_targets,
                    total.averaged_targets,
                    total.expanded_without_target,
                ]
            ],
        ),
        markdown_table(
            ["Sizes", *sizes, "Mean"],
            [
                [
                    "expanded descendants behind averaged targets",
                    *total.averaged_descendants.buckets,
                    f"{total.averaged_descendants.mean_size:.1f}",
                ],
                [
                    "expanded subtree of every expanded node",
                    *total.expanded_subtree_sizes.buckets,
                    f"{total.expanded_subtree_sizes.mean_size:.1f}",
                ],
            ],
        ),
        markdown_table(
            [
                "GRPO groups",
                "Samples",
                "Mixed rewards (dense)",
                "Mixed rewards (outcome only)",
                "Local reward",
                "Global reward (beta G)",
                "Positive local reward off the proof graph",
            ],
            [
                [
                    total.groups,
                    total.group_samples,
                    share(total.groups_with_mixed_rewards, total.groups),
                    share(total.outcome_groups_with_mixed_rewards, total.groups),
                    f"{total.local_reward:,.1f}",
                    f"{total.global_reward:,.1f}",
                    share(total.positive_local_reward_off_proof_graph, total.positive_local_reward),
                ]
            ],
        ),
    ]
    return "\n\n".join(sections)


def render_markdown(report: GraphReport) -> str:
    return "# Search-graph labels\n\n" + "\n\n".join(render_run(run) for run in report.runs) + "\n"


def main() -> None:
    parsed = parse_arguments()
    readout = RemainingStepsReadout()
    target_config = ValueTargetConfig()
    reward_config = RewardConfig()
    runs = tuple(run_report(directory, readout, target_config, reward_config) for directory in parsed.trees)
    report = GraphReport(readout, target_config, reward_config, runs)
    markdown = render_markdown(report)
    print(markdown)
    if parsed.output is not None:
        parsed.output.mkdir(parents=True, exist_ok=True)
        (parsed.output / "summary.json").write_text(
            json.dumps(dataclasses.asdict(report), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        (parsed.output / "README.md").write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
