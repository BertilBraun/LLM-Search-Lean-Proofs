"""Checks the study's launchers run before they start anything (deployment/probe_runs.sh, deployment/arm_loop.sh;
src/lean_search/rl/node_pinning.py).

    python experiments/node_checks.py pinning --background-cpus 52   # the pinned set; exit 1 if it will not do
    python experiments/node_checks.py servers-free                   # exit 1 while the lock is held or a loop runs
                                                                      # (or a process of RESPECTED_PID_FILES lives)
    deployment/background.sh python experiments/node_checks.py record --directory <run directory>

pinning checks deployment/background.sh's set (the last N of all the host's CPUs) against the CPUs this process may
use and the cgroup quota (N must stay below it). record appends the CPUs the (pinned) process may use, the host's CPU
count, the quota and BACKGROUND_CPUS to <run directory>/pinning.jsonl: run it through background.sh right before the
job, as the job itself runs.
"""

import argparse
import os
import sys
from pathlib import Path

from lean_search.policy.serving_lock import lock_holder, serving_lock_path
from lean_search.rl.node_pinning import append_pinning, background_set, current_pinning, pinning_refusals
from lean_search.rl.probe_evaluation import running_loops

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pinning").add_argument("--background-cpus", type=int, required=True)
    commands.add_parser("servers-free")
    commands.add_parser("record").add_argument("--directory", type=Path, required=True)
    return parser.parse_args()


def ancestors(process_id: int) -> set[int]:
    """The process and those it descends from."""
    found = set()
    while process_id > 1 and process_id not in found:
        found.add(process_id)
        try:
            stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
        except OSError:
            break
        process_id = int(stat.rsplit(")", 1)[1].split()[1])
    return found


def respected_processes(pid_files: str) -> list[tuple[str, int]]:
    """The live processes the colon-separated pid files name, except this command's own ancestors (a supervisor that
    starts the probe runs itself)."""
    own = ancestors(os.getpid())
    live = []
    for pid_file in filter(None, pid_files.split(":")):
        try:
            text = Path(pid_file).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text.isdigit() and int(text) not in own and Path(f"/proc/{text}").exists():
            live.append((pid_file, int(text)))
    return live


def refuse(refusals: list[str]) -> None:
    if refusals:
        print("\n".join(refusals), file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "pinning":
            record = current_pinning()
            pinned = background_set(arguments.background_cpus, record.cpu_count)
            print(
                f"background.sh pins CPUs {pinned[0]}-{pinned[-1]} ({len(pinned)} of {record.cpu_count}); this process "
                f"may use {len(record.affinity)}; cgroup quota {record.quota_cores} cores"
            )
            refuse(pinning_refusals(arguments.background_cpus, record.cpu_count, record.affinity, record.quota_cores))
        case "servers-free":
            holder = lock_holder(serving_lock_path(CHECKPOINTS_DIRECTORY))
            refusals = [f"Process {holder} holds the serving lock: something else uses the servers."] if holder else []
            refusals += [f"A loop runs: {loop}" for loop in running_loops(RUNS_DIRECTORY).running]
            refusals += [
                f"{pid_file} names a live process ({process_id}): something else may use the servers."
                for pid_file, process_id in respected_processes(os.environ.get("RESPECTED_PID_FILES", ""))
            ]
            refuse(refusals)
        case "record":
            print(append_pinning(arguments.directory))


if __name__ == "__main__":
    main()
