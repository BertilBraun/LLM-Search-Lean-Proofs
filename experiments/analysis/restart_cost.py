"""Measurement: what a wall-clock kill costs the caller, with and without warm spare processes
(`LeanReplPool(spare_processes=...)`). Each worker holds one pooled REPL, opens a trivial statement and runs `sleep`
(heartbeats do not count sleeping) until the wall clock kills the process; the cost of a kill is the call's seconds
beyond the wall clock: the kill, the new process and its header import (or the swap to a spare). Also reports the
memory of a REPL after the header and of a ready spare.

    deployment/background.sh python experiments/analysis/restart_cost.py --header-file <file with the header> \
        --workers 16 --kills 5 --spares 0,8 --output /workspace/runs/search_efficiency/restart_cost
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from lean_search.lean import LeanReplConfig, LeanReplPool, LeanTimeout, ProofState
from lean_search.lean.repl import read_memory_usage

STATEMENT = "theorem lean_search_restart_probe : True := by\n"
SPARE_WAIT_SECONDS = 600.0


@dataclass(frozen=True)
class Kill:
    spares: int
    worker: int
    seconds_beyond_wall_clock: float
    swapped: bool


@dataclass(frozen=True)
class Memory:
    spares: int
    pooled_resident_bytes: int
    pooled_anonymous_bytes: int
    spare_resident_bytes: int | None
    spare_anonymous_bytes: int | None


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--header-file", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--kills", type=int, default=5)
    parser.add_argument("--spares", default="0,8")
    parser.add_argument("--wall-clock-seconds", type=float, default=5.0)
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def measure(header: str, spares: int, arguments: argparse.Namespace) -> tuple[list[Kill], Memory]:
    config = LeanReplConfig(tactic_timeout_seconds=arguments.wall_clock_seconds, forbidden_tokens=frozenset())
    kills: list[Kill] = []
    async with LeanReplPool(arguments.workers, config, spare_processes=spares) as pool:
        await pool.start([header])
        if pool.spares is not None:
            async with asyncio.timeout(SPARE_WAIT_SECONDS):
                while pool.spares.ready < spares:
                    await asyncio.sleep(1.0)
        pooled = read_memory_usage(pool.repls[0].process_id or 0)
        spare_usage = None
        if pool.spares is not None and pool.spares.ready:
            spare_usage = read_memory_usage(pool.spares.ready_process_ids()[0])
        memory = Memory(
            spares,
            pooled.resident_bytes,
            pooled.anonymous_bytes,
            None if spare_usage is None else spare_usage.resident_bytes,
            None if spare_usage is None else spare_usage.anonymous_bytes,
        )

        async def worker(index: int) -> None:
            async with pool.acquire() as repl:
                start = await repl.start_proof(STATEMENT, header)
                assert isinstance(start.outcome, ProofState), start.outcome
                for _ in range(arguments.kills):
                    swaps_before = repl.spare_swaps
                    started = time.monotonic()
                    result = await repl.apply_tactic(start.outcome, "sleep 1000000", 50_000)
                    seconds = time.monotonic() - started
                    assert isinstance(result.outcome, LeanTimeout) and result.outcome.wall_clock, result.outcome
                    beyond = seconds - arguments.wall_clock_seconds
                    kills.append(Kill(spares, index, beyond, repl.spare_swaps > swaps_before))
                    await asyncio.sleep(arguments.pause_seconds)

        await asyncio.gather(*(worker(index) for index in range(arguments.workers)))
    return kills, memory


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def summary(kills: list[Kill], memories: list[Memory], arguments: argparse.Namespace) -> str:
    lines = [
        "# Cost of a wall-clock kill to the caller",
        "",
        f"{arguments.workers} workers, {arguments.kills} kills each, wall clock {arguments.wall_clock_seconds:g} s, "
        f"{arguments.pause_seconds:g} s between a worker's kills.",
        "",
        "| spares | kills | swapped | median s | p10 s | p90 s | mean s |",
        "|---|---|---|---|---|---|---|",
    ]
    for spares in sorted({kill.spares for kill in kills}):
        seconds = [kill.seconds_beyond_wall_clock for kill in kills if kill.spares == spares]
        swapped = sum(kill.swapped for kill in kills if kill.spares == spares)
        lines.append(
            f"| {spares} | {len(seconds)} | {swapped} | {statistics.median(seconds):.2f} | "
            f"{quantile(seconds, 0.1):.2f} | {quantile(seconds, 0.9):.2f} | {statistics.mean(seconds):.2f} |"
        )
    lines += [
        "",
        "| spares | pooled REPL resident / private GiB | ready spare resident / private GiB |",
        "|---|---|---|",
    ]
    for memory in memories:
        spare = (
            "-"
            if memory.spare_resident_bytes is None or memory.spare_anonymous_bytes is None
            else f"{memory.spare_resident_bytes / 2**30:.2f} / {memory.spare_anonymous_bytes / 2**30:.2f}"
        )
        lines.append(
            f"| {memory.spares} | {memory.pooled_resident_bytes / 2**30:.2f} / "
            f"{memory.pooled_anonymous_bytes / 2**30:.2f} | {spare} |"
        )
    return "\n".join(lines) + "\n"


async def run(arguments: argparse.Namespace) -> None:
    header = arguments.header_file.read_text(encoding="utf-8")
    kills: list[Kill] = []
    memories: list[Memory] = []
    for spares in [int(count) for count in arguments.spares.split(",")]:
        measured, memory = await measure(header, spares, arguments)
        kills += measured
        memories.append(memory)
        print(summary(kills, memories, arguments), flush=True)
    arguments.output.mkdir(parents=True, exist_ok=True)
    records = [asdict(kill) for kill in kills] + [asdict(memory) for memory in memories]
    (arguments.output / "records.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    (arguments.output / "summary.md").write_text(summary(kills, memories, arguments), encoding="utf-8")


def main() -> None:
    asyncio.run(run(parse_arguments()))


if __name__ == "__main__":
    main()
