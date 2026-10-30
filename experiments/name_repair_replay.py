"""Stage 0 of name repair, offline (src/lean_search/rl/name_repair_replay.py): the loop's recorded policy blocks that
failed on unknown dotted names, repaired at each difflib threshold and run again in Lean from their recorded parent
state; per threshold the share made valid and the Lean seconds it cost.

    python experiments/name_repair_replay.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1 \
        --output $LEAN_SEARCH_RUNS/grpo_name_repair_replay --phases 2 3 --max-failures 600 --concurrency 8

Reads the tree store ($LEAN_SEARCH_RUNS/<loop>/trees), a seeded sample of at most --max-failures failures; headers
come from the loop's curriculum statements (verified and indexed). Runs on its own pool of --concurrency REPLs, beside
the loop at modest concurrency. Writes replays.jsonl, summary.json and report.md to --output.
"""

import argparse
import asyncio
import os
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.known_proofs import read_index, read_verified
from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.identifiers import environment_names, name_scope, shared_name_repairer
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.name_repair_replay import (
    FailureReplay,
    ReplayRun,
    StateBuilder,
    ThresholdSummary,
    UnknownNameFailure,
    repaired_texts,
    replay_block,
    summary_table,
    threshold_summaries,
    unknown_name_failures,
)
from lean_search.rl.tree_store import TreeStore
from lean_search.search.records import TreeRecord, read_tree, to_json

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
# The search's own limits for a policy block (visible_student_v2.toml).
HEARTBEATS = 50_000
TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class ReplaySummary:
    failures_found: int
    sampled: int
    # Their parent state rebuilt as recorded.
    replayable: int
    thresholds: tuple[ThresholdSummary, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phases", type=int, nargs="+", help="default: every phase")
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.7, 0.8, 0.85, 0.9])
    parser.add_argument("--max-failures", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def statement_headers(loop_directory: Path) -> dict[str, str]:
    curriculum = load_loop_config(loop_directory / "loop.toml").statements.curriculum
    verified, _ = read_verified(DATA_DIRECTORY / curriculum.verified)
    statements = [record.statement for record in verified]
    if curriculum.unverified and (DATA_DIRECTORY / curriculum.unverified).exists():
        statements.extend(entry.statement for entry in read_index(DATA_DIRECTORY / curriculum.unverified))
    return {problem_name(statement): statement.header for statement in statements}


async def replay_tree(
    pool: LeanReplPool,
    record: TreeRecord,
    header: str,
    failures: Sequence[UnknownNameFailure],
    thresholds: Sequence[float],
) -> list[FailureReplay]:
    async with pool.acquire() as repl:
        names = await environment_names(repl, header)
        repairers = [shared_name_repairer(names, threshold) for threshold in thresholds]
        scope = name_scope(header, record.statement)
        namespaces = () if scope is None else scope.namespaces
        builder = StateBuilder(repl, record, header)
        replays = []
        for failure in failures:
            texts = await asyncio.to_thread(repaired_texts, failure, repairers, namespaces)
            state = await builder.state(failure.node_id)
            runs: dict[str, ReplayRun] = {}
            if state is not None:
                for text in dict.fromkeys(text for text in texts if text is not None):
                    runs[text] = await replay_block(repl, state, text, HEARTBEATS, TIMEOUT_SECONDS)
            replays.append(FailureReplay(failure, state is not None, texts, runs))
        return replays


async def main_async(arguments: argparse.Namespace) -> None:
    store = TreeStore(arguments.loop_directory / "trees")
    entries = [entry for entry in store.entries if arguments.phases is None or entry.phase in arguments.phases]
    headers = statement_headers(arguments.loop_directory)
    found: list[tuple[str, UnknownNameFailure]] = []
    for entry in entries:
        if entry.problem_name in headers:
            record = read_tree(store.directory / entry.file, texts=False)
            found.extend((entry.file, failure) for failure in unknown_name_failures(record))
    print(f"{len(found)} unknown-name failures with a dotted name in {len(entries)} trees", flush=True)
    chosen = random.Random(arguments.seed).sample(found, min(len(found), arguments.max_failures))
    by_tree: dict[str, list[UnknownNameFailure]] = {}
    for file, failure in chosen:
        by_tree.setdefault(file, []).append(failure)
    records = {file: read_tree(store.directory / file, texts=False) for file in by_tree}
    async with LeanReplPool(arguments.concurrency, LeanReplConfig()) as pool:
        await pool.start(sorted({headers[record.problem_name] for record in records.values()}))

        async def replay_one(file: str) -> list[FailureReplay]:
            record = records[file]
            return await replay_tree(pool, record, headers[record.problem_name], by_tree[file], arguments.thresholds)

        replays = [
            replay for found_replays in await asyncio.gather(*map(replay_one, by_tree)) for replay in found_replays
        ]
    summaries = threshold_summaries(replays, arguments.thresholds)
    arguments.output.mkdir(parents=True, exist_ok=True)
    with (arguments.output / "replays.jsonl").open("w", encoding="utf-8") as lines:
        lines.writelines(to_json(replay) + "\n" for replay in replays)
    replayable = sum(replay.replayable for replay in replays)
    summary = ReplaySummary(len(found), len(replays), replayable, tuple(summaries))
    write_json_atomically(arguments.output / "summary.json", summary)
    text = (
        f"# Name repair replay\n\n{len(found)} policy blocks failed on an unknown dotted name; {len(replays)} sampled, "
        f"{replayable} with their parent state rebuilt.\n\n" + summary_table(summaries)
    )
    (arguments.output / "report.md").write_text(text, encoding="utf-8")
    print(text, flush=True)


def main() -> None:
    asyncio.run(main_async(parse_arguments()))


if __name__ == "__main__":
    main()
