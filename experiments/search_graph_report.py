"""Label recorded search trees as graphs and report edge kinds, the proof graph, tactics, value targets and groups.

    python experiments/search_graph_report.py --trees runs/phase5_expansions_visible_student/trees \
        --output runs/search_graph_report_visible_student

Reads <directory>/*.json.gz for each --trees directory; with --output writes summary.json (run totals and per-tree
statistics) and README.md there. Search-time value estimates come from each node's recorded h. Trees written before
`Edge.tactic_goals` know only each edge's final state (src/lean_search/rl/README.md, "Per-tactic labels").
"""

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from lean_search.rl.grpo_groups import RewardConfig, policy_groups
from lean_search.rl.tree_statistics import GraphStatistics, TreeStatistics, graph_statistics, total_statistics
from lean_search.search import read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.search.summary import markdown_table
from lean_search.search.tactic_labels import TacticLabelCounts, policy_tactics
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
    trees = []
    for path in sorted(directory.glob("*.json.gz")):
        record = read_tree(path)
        labels = label_graph(record)
        estimates = recorded_estimates(record, readout)
        targets = value_targets(record, labels, estimates, target_config)
        tactics = policy_tactics(record, labels, reward_config.off_graph_min_expanded_nodes)
        groups = policy_groups(record, labels, tactics, estimates, reward_config)
        statistics = graph_statistics(record, labels, targets, tactics, groups)
        trees.append(TreeStatistics(record.problem_name, statistics))
    return RunReport(str(directory), total_statistics([tree.statistics for tree in trees]), tuple(trees))


def share(count: float, total: float) -> str:
    return f"{count:,.0f} ({count / total:.1%})" if total else "0"


def tactic_shares(counts: TacticLabelCounts) -> list[str]:
    return [share(getattr(counts, field.name), counts.total) for field in dataclasses.fields(counts)]


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
            [
                "Proof graph targets",
                "Off-graph targets",
                "q averaging descendants",
                "Without q",
                "Expanded, capped",
            ],
            [
                [
                    total.proof_graph_targets,
                    total.off_graph_targets,
                    total.targets_averaging_descendants,
                    total.targets_without_value_part,
                    total.expanded_without_target,
                ]
            ],
        ),
        markdown_table(
            ["Sizes", *sizes, "Mean"],
            [
                [
                    "expanded subtree behind off-graph targets",
                    *total.off_graph_subtree_sizes.buckets,
                    f"{total.off_graph_subtree_sizes.mean_size:.1f}",
                ],
                [
                    "expanded subtree of every expanded node",
                    *total.expanded_subtree_sizes.buckets,
                    f"{total.expanded_subtree_sizes.mean_size:.1f}",
                ],
            ],
        ),
        markdown_table(
            ["Proofs", "per solved tree", "Tactics per proof", "Blocks per proof", "Harvest expansions", "Explored"],
            [
                [
                    total.proofs,
                    f"{total.proofs / max(1, total.solved_trees):.2f}",
                    f"{total.proof_tactics / max(1, total.proofs):.2f}",
                    f"{total.proof_blocks / max(1, total.proofs):.2f}",
                    total.harvest_expansions,
                    total.exploration_expansions,
                ]
            ],
        ),
        markdown_table(
            ["Tactics", *(field.name for field in dataclasses.fields(TacticLabelCounts)), "Total"],
            [
                ["every policy sample", *tactic_shares(total.policy_tactics), f"{total.policy_tactics.total:,}"],
                ["group samples", *tactic_shares(total.group_tactics), f"{total.group_tactics.total:,}"],
            ],
        ),
        markdown_table(
            [
                "GRPO groups",
                "Samples",
                "With a signal",
                "Left out without a policy proof",
                "Global reward (1 − λ) G",
                "Local reward λ L",
            ],
            [
                [
                    total.groups,
                    total.group_samples,
                    share(total.groups_with_signal, total.groups),
                    total.groups_without_policy_proof,
                    f"{total.global_reward:,.1f}",
                    f"{total.local_reward:,.1f}",
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
