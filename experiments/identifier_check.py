"""Run the pre-Lean identifier check over recorded policy blocks: false rejections and caught unknown names.

    python experiments/identifier_check.py --trees runs/phase5_expansions_visible_student/trees \
        --output runs/identifier_check_visible_student

Every block, or valid prefix, that Lean accepted and the check rejects is a false rejection. Recorded failures whose
first error is an unknown identifier or constant count as caught when the check rejects the same tactic. Headers come
from miniF2F by problem name; the environment's names are exported once through a REPL (cached under
$LEAN_SEARCH_DATA/lean). Writes summary.json and README.md to --output.
"""

import argparse
import asyncio
import dataclasses
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lean_search.data import load_minif2f
from lean_search.lean import LeanRepl
from lean_search.lean.identifiers import IdentifierChecker, environment_names, name_scope
from lean_search.lean.plans import plain_plan
from lean_search.search import EdgeOutcome, StepSource, TreeRecord, read_tree
from lean_search.search.summary import markdown_table

UNKNOWN_NAME = re.compile(r"unknown (?:identifier|constant) '?(?P<name>[^'\s]+)'?")
EXAMPLES = 40


@dataclass(frozen=True)
class Example:
    problem_name: str
    edge_id: int
    tactic: str
    names: tuple[str, ...]


@dataclass
class CheckCounts:
    blocks: int = 0
    unchecked_trees: int = 0
    accepted_blocks: int = 0
    accepted_blocks_rejected: int = 0
    accepted_prefixes: int = 0
    accepted_prefixes_rejected: int = 0
    unknown_name_failures: int = 0
    unknown_name_failures_caught: int = 0
    unknown_name_failures_caught_same_name: int = 0
    unknown_name_failures_caught_earlier: int = 0
    unknown_local_failures: int = 0
    unknown_local_failures_caught: int = 0
    unknown_library_failures: int = 0
    unknown_library_failures_caught: int = 0
    other_failures_rejected: int = 0


@dataclass(frozen=True)
class CheckReport:
    counts: CheckCounts
    false_rejection_rate: float
    catch_rate: float
    false_rejections: tuple[Example, ...]
    missed: tuple[Example, ...]
    false_rejected_names: tuple[tuple[str, int], ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", nargs="+", required=True, type=Path)
    parser.add_argument("--limit", type=int, help="at most this many trees per directory")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def is_local_name(name: str) -> bool:
    return "." not in name and (name.startswith("h") or name in ("ih", "this") or len(name) <= 2)


def check_tree(record: TreeRecord, header: str, checker: IdentifierChecker, report: "ReportBuilder") -> None:
    scope = name_scope(header, record.statement)
    if scope is None:
        report.counts.unchecked_trees += 1
        return
    for edge in record.edges:
        if edge.source != StepSource.POLICY or edge.outcome in (EdgeOutcome.REPEATED, EdgeOutcome.REJECTED):
            continue
        report.counts.blocks += 1
        tactics = plain_plan(edge.text).texts
        if edge.total_tactics != len(tactics):
            continue
        unknown = checker.first_unknown(tactics, record.nodes[edge.parent_id].goals, scope)
        counts = report.counts
        if edge.failure is None:
            counts.accepted_blocks += 1
            if unknown is not None:
                counts.accepted_blocks_rejected += 1
                report.false_rejection(record, edge.edge_id, tactics[unknown.tactic_index], unknown.names)
            continue
        if edge.applied_tactics:
            counts.accepted_prefixes += 1
            if unknown is not None and unknown.tactic_index < edge.applied_tactics:
                counts.accepted_prefixes_rejected += 1
                report.false_rejection(record, edge.edge_id, tactics[unknown.tactic_index], unknown.names)
                continue
        first_error = edge.failure.message.strip().split("\n")[0]
        match = UNKNOWN_NAME.search(first_error)
        if match is None:
            counts.other_failures_rejected += unknown is not None and unknown.tactic_index == edge.applied_tactics
            continue
        name = match["name"]
        local = is_local_name(name)
        counts.unknown_name_failures += 1
        counts.unknown_local_failures += local
        counts.unknown_library_failures += not local
        caught = unknown is not None and unknown.tactic_index == edge.applied_tactics
        counts.unknown_name_failures_caught += caught
        counts.unknown_local_failures_caught += caught and local
        counts.unknown_library_failures_caught += caught and not local
        counts.unknown_name_failures_caught_same_name += caught and name in unknown.names
        counts.unknown_name_failures_caught_earlier += (
            unknown is not None and unknown.tactic_index < edge.applied_tactics
        )
        if not caught and edge.applied_tactics < len(tactics):
            report.missed_example(record, edge.edge_id, tactics[edge.applied_tactics], (name,))


@dataclass
class ReportBuilder:
    counts: CheckCounts = dataclasses.field(default_factory=CheckCounts)
    false_rejections: list[Example] = dataclasses.field(default_factory=list)
    missed: list[Example] = dataclasses.field(default_factory=list)
    false_rejected_names: Counter[str] = dataclasses.field(default_factory=Counter)

    def false_rejection(self, record: TreeRecord, edge_id: int, tactic: str, names: tuple[str, ...]) -> None:
        self.false_rejected_names.update(names)
        if len(self.false_rejections) < EXAMPLES:
            self.false_rejections.append(Example(record.problem_name, edge_id, tactic, names))

    def missed_example(self, record: TreeRecord, edge_id: int, tactic: str, names: tuple[str, ...]) -> None:
        if len(self.missed) < EXAMPLES:
            self.missed.append(Example(record.problem_name, edge_id, tactic, names))

    def report(self) -> CheckReport:
        counts = self.counts
        accepted = counts.accepted_blocks + counts.accepted_prefixes
        rejected = counts.accepted_blocks_rejected + counts.accepted_prefixes_rejected
        return CheckReport(
            counts=counts,
            false_rejection_rate=rejected / accepted if accepted else 0.0,
            catch_rate=counts.unknown_name_failures_caught / counts.unknown_name_failures
            if counts.unknown_name_failures
            else 0.0,
            false_rejections=tuple(self.false_rejections),
            missed=tuple(self.missed),
            false_rejected_names=tuple(self.false_rejected_names.most_common(40)),
        )


def readme(report: CheckReport) -> str:
    counts = report.counts
    rows = [[field.name, str(getattr(counts, field.name))] for field in dataclasses.fields(counts)]
    lines = [
        "# Identifier check on recorded policy blocks",
        "",
        f"False rejections: {report.false_rejection_rate:.4%} of accepted blocks and prefixes; "
        f"caught unknown-name failures: {report.catch_rate:.1%}.",
        "",
        markdown_table(["count", "value"], rows),
        "",
        "## False rejections (examples)",
        "",
        *(
            f"- `{example.problem_name}` edge {example.edge_id}: {example.names} in `{example.tactic[:200]}`"
            for example in report.false_rejections
        ),
        "",
        "## Missed unknown names (examples)",
        "",
        *(
            f"- `{example.problem_name}` edge {example.edge_id}: {example.names} in `{example.tactic[:200]}`"
            for example in report.missed
        ),
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    arguments = parse_arguments()
    headers = {problem.name: problem.header for problem in load_minif2f()}
    builder = ReportBuilder()
    async with LeanRepl() as repl:
        names = await environment_names(repl, next(iter(headers.values())))
    checker = IdentifierChecker(names)
    for directory in arguments.trees:
        paths = sorted(directory.glob("*.json.gz"))[: arguments.limit]
        for path in paths:
            record = read_tree(path)
            check_tree(record, headers[record.problem_name], checker, builder)
    report = builder.report()
    print(json.dumps(dataclasses.asdict(report.counts), indent=2))
    print(f"false rejection rate {report.false_rejection_rate:.4%}, catch rate {report.catch_rate:.1%}")
    print("false rejected names:", report.false_rejected_names)
    for example in report.false_rejections:
        print("FALSE", example)
    for example in report.missed:
        print("MISSED", example)
    if arguments.output is not None:
        arguments.output.mkdir(parents=True, exist_ok=True)
        (arguments.output / "summary.json").write_text(json.dumps(dataclasses.asdict(report), indent=2))
        (arguments.output / "README.md").write_text(readme(report))


if __name__ == "__main__":
    asyncio.run(main())
