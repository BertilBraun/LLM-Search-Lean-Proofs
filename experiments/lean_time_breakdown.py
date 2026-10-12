"""Where a search run's Lean time goes: sweep tactics, policy candidates by outcome and family, limits and caching.

    python experiments/lean_time_breakdown.py --run phase3_astar_v0_sft_v2 [--sweep omega,constructor,...]

Reads $LEAN_SEARCH_RUNS/<run>/trees/*.json.gz and prints markdown tables. Edge Lean seconds are wall-clock inside the
REPL (they include the restart and replay a wall-clock kill causes); `--sweep` names a smaller automation sweep whose
saving and lost proof steps are estimated from the trees.
"""

import argparse
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.lean.text import normalize_goal
from lean_search.search import EdgeOutcome, FailureKind, NodeStatus, StepSource, TreeRecord, read_tree
from lean_search.search.summary import markdown_table

FIRST_WORD = re.compile(r"[\w.'?!]+")
LIMITS_SECONDS = (1.0, 2.0, 5.0)


@dataclass
class Bucket:
    attempts: int = 0
    seconds: float = 0.0
    children: int = 0
    timeouts: int = 0
    proof_steps: int = 0


@dataclass
class Totals:
    expansions: int = 0
    root_seconds: float = 0.0
    verification_seconds: float = 0.0
    by_tactic: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_outcome: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_family: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    seconds_over_limit: dict[float, float] = field(default_factory=lambda: defaultdict(float))
    proofs_needing_over_limit: dict[float, int] = field(default_factory=lambda: defaultdict(int))
    sweep_keys: Counter[tuple[str, str]] = field(default_factory=Counter)
    sweep_seconds_by_key: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--sweep", default="omega,constructor,rfl,field_simp,ring_nf,simp_all,nlinarith")
    return parser.parse_args()


def policy_outcome(outcome: EdgeOutcome, failure: FailureKind | None) -> str:
    match failure:
        case FailureKind.HEARTBEAT_TIMEOUT | FailureKind.WALL_CLOCK_TIMEOUT:
            return "timeout"
        case FailureKind.REPL_FAILURE:
            return "repl failure"
        case FailureKind.ERROR if outcome == EdgeOutcome.CHILD:
            return "valid prefix, then error"
        case FailureKind.ERROR:
            return "error"
        case _:
            return {EdgeOutcome.CHILD: "valid", EdgeOutcome.DUPLICATE: "valid, duplicate"}.get(outcome, "not run")


def add(totals: Totals, tree: TreeRecord) -> None:
    totals.expansions += tree.result.accounting.expansions
    totals.verification_seconds += tree.result.accounting.verification_seconds
    totals.root_seconds += tree.nodes[0].step_lean_seconds
    goals_by_node = {node.node_id: node.goals for node in tree.nodes}
    proof_edges = {node.edge_id for node in tree.nodes if node.status == NodeStatus.PROVED and node.edge_id is not None}
    slowest_proof_step = max((edge.lean_seconds for edge in tree.edges if edge.edge_id in proof_edges), default=0.0)
    for limit in LIMITS_SECONDS:
        totals.proofs_needing_over_limit[limit] += slowest_proof_step > limit
    for edge in tree.edges:
        failure = edge.failure.kind if edge.failure else None
        on_proof = edge.edge_id in proof_edges
        timed_out = failure in (FailureKind.HEARTBEAT_TIMEOUT, FailureKind.WALL_CLOCK_TIMEOUT)
        buckets = []
        if edge.source == StepSource.AUTOMATION:
            buckets.append(totals.by_tactic[edge.text])
            key = (" ".join(normalize_goal(goal) for goal in goals_by_node[edge.parent_id]), edge.text)
            totals.sweep_keys[key] += 1
            totals.sweep_seconds_by_key[key] += edge.lean_seconds
        else:
            buckets.append(totals.by_outcome[policy_outcome(edge.outcome, failure)])
            match = FIRST_WORD.match(edge.text.strip())
            buckets.append(totals.by_family[match.group(0) if match else "?"])
        for bucket in buckets:
            bucket.attempts += 1
            bucket.seconds += edge.lean_seconds
            bucket.children += edge.outcome == EdgeOutcome.CHILD
            bucket.timeouts += timed_out
            bucket.proof_steps += on_proof
        for limit in LIMITS_SECONDS:
            totals.seconds_over_limit[limit] += max(0.0, edge.lean_seconds - limit)


def bucket_rows(buckets: dict[str, Bucket], total_seconds: float, expansions: int, limit: int) -> list[list[object]]:
    ordered = sorted(buckets.items(), key=lambda item: -item[1].seconds)[:limit]
    return [
        [
            f"`{name}`",
            f"{bucket.attempts:,}",
            f"{bucket.seconds / expansions:.2f}",
            f"{bucket.seconds / total_seconds:.1%}",
            f"{bucket.seconds / max(1, bucket.attempts):.2f}",
            f"{bucket.children:,}",
            f"{bucket.timeouts:,}",
            f"{bucket.proof_steps:,}",
        ]
        for name, bucket in ordered
    ]


def main() -> None:
    arguments = parse_arguments()
    totals = Totals()
    trees = sorted((Path(os.environ["LEAN_SEARCH_RUNS"]) / arguments.run / "trees").glob("*.json.gz"))
    for path in trees:
        add(totals, read_tree(path))
    sweep_seconds = sum(bucket.seconds for bucket in totals.by_tactic.values())
    policy_seconds = sum(bucket.seconds for bucket in totals.by_outcome.values())
    total = sweep_seconds + policy_seconds + totals.root_seconds + totals.verification_seconds
    per = totals.expansions
    headers = ["", "Attempts", "s / expansion", "Share", "s / attempt", "Children", "Timeouts", "Proof steps"]
    print(f"# Lean time of `{arguments.run}`: {len(trees)} trees, {per:,} expansions, {total / per:.2f} s/expansion\n")
    print(
        markdown_table(
            ["Part", "s / expansion", "Share"],
            [
                [name, f"{seconds / per:.2f}", f"{seconds / total:.1%}"]
                for name, seconds in (
                    ("automation sweep", sweep_seconds),
                    ("policy candidates", policy_seconds),
                    ("root statement", totals.root_seconds),
                    ("proof verification", totals.verification_seconds),
                )
            ],
        )
    )
    print("\n## Sweep tactics\n")
    print(markdown_table(["Tactic", *headers[1:]], bucket_rows(totals.by_tactic, total, per, 20)))
    print("\n## Policy candidates by outcome\n")
    print(markdown_table(["Outcome", *headers[1:]], bucket_rows(totals.by_outcome, total, per, 10)))
    print("\n## Policy candidates by first tactic\n")
    print(markdown_table(["Tactic", *headers[1:]], bucket_rows(totals.by_family, total, per, 15)))
    sweep = set(arguments.sweep.split(","))
    dropped = {name: bucket for name, bucket in totals.by_tactic.items() if name not in sweep}
    print(
        f"\nSweep {sorted(sweep)}: saves {sum(bucket.seconds for bucket in dropped.values()) / per:.2f} s/expansion "
        f"({sum(bucket.seconds for bucket in dropped.values()) / total:.1%}); the dropped tactics were "
        f"{sum(bucket.proof_steps for bucket in dropped.values())} proof steps."
    )
    print("\n## Per-call limits\n")
    print(
        markdown_table(
            ["Limit s", "Saved s / expansion", "Share", "Proofs with a slower step"],
            [
                [
                    f"{limit:g}",
                    f"{totals.seconds_over_limit[limit] / per:.2f}",
                    f"{totals.seconds_over_limit[limit] / total:.1%}",
                    totals.proofs_needing_over_limit[limit],
                ]
                for limit in LIMITS_SECONDS
            ],
        )
    )
    repeated = sum(
        seconds * (totals.sweep_keys[key] - 1) / totals.sweep_keys[key]
        for key, seconds in totals.sweep_seconds_by_key.items()
    )
    print(
        f"\nSweep calls on a (goals, tactic) pair already run in this or another tree: "
        f"{sum(count - 1 for count in totals.sweep_keys.values()):,} of {sum(totals.sweep_keys.values()):,}, "
        f"{repeated / per:.3f} s/expansion ({repeated / total:.1%}) a cache could save."
    )


if __name__ == "__main__":
    main()
