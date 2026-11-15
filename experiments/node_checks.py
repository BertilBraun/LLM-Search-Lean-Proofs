"""Checks the study's launchers run before they start anything (deployment/probe_runs.sh, deployment/arm_loop.sh;
src/lean_search/rl/node_pinning.py).

    python experiments/node_checks.py pinning         # the environment's CPU layout; exit 1 if it will not do
    python experiments/node_checks.py servers-free    # exit 1 while the lock is held or a loop runs
                                                      # (or a process of RESPECTED_PID_FILES lives)
    deployment/background.sh python experiments/node_checks.py record --directory <run directory>

pinning prints the node environment file and its settings, BACKGROUND_CPUS, BACKGROUND_CPU_LIST, SERVER_CPU_LIST and
TRAINING_CPU_LIST as they take effect, the cpuset and the quota, and checks the layout (`node_pinning.pinning_check`):
exactly one background setting, every set within the CPUs this process may use, the background set below the quota
with SERVER_RESERVE_CORES (8 by default; set it to override, recorded in each run's pinning.jsonl) beside it, and on
physical cores of its own. record appends
the pinning of the (pinned) process to <run directory>/pinning.jsonl.
"""

import argparse
import os
import sys
from pathlib import Path

from lean_search.monitoring.cpu_layout import cpu_list_text, thread_siblings
from lean_search.policy.serving_lock import lock_holder, serving_lock_path
from lean_search.rl.node_pinning import (
    PinningRecord,
    append_pinning,
    background_set,
    current_pinning,
    pinning_check,
    server_reserve_cores,
)
from lean_search.rl.probe_evaluation import running_loops

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pinning")
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


def setting_text(value: int | str | None) -> str:
    return "(unset)" if value is None else str(value)


def node_environment_lines(record: PinningRecord) -> list[str]:
    if record.node_environment is None:
        return ["No node environment file."]
    settings = Path(record.node_environment).read_text(encoding="utf-8").splitlines()
    lines = [f"Node environment {record.node_environment} (sha256 {record.node_environment_sha256}):"]
    return lines + [f"  {line}" for line in settings if line.strip() and not line.lstrip().startswith("#")]


def pinning_summary(record: PinningRecord) -> str:
    quota = "none" if record.quota_cores is None else f"{record.quota_cores:g} cores"
    return (
        f"BACKGROUND_CPUS={setting_text(record.background_cpus)} "
        f"BACKGROUND_CPU_LIST={setting_text(record.background_cpu_list)} SERVER_CPU_LIST={record.server_cpu_list} "
        f"TRAINING_CPU_LIST={record.training_cpu_list}; this process may use CPUs {cpu_list_text(record.affinity)} "
        f"({len(record.affinity)} of {record.cpu_count}); cpuset {record.allowed_cpu_list}; cgroup quota {quota}"
    )


def refuse(refusals: list[str]) -> None:
    if refusals:
        print("\n".join(refusals), file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "pinning":
            record = current_pinning()
            print("\n".join([*node_environment_lines(record), pinning_summary(record)]))
            try:
                check = pinning_check(record, thread_siblings(), server_reserve_cores())
            except ValueError as error:
                raise SystemExit(str(error)) from error
            for warning in check.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            refuse(list(check.refusals))
            pinned = background_set(record.background_cpus, record.background_cpu_list, record.cpu_count)
            print(f"background.sh pins CPUs {cpu_list_text(pinned)} ({len(pinned)} of {record.cpu_count})")
            if record.quota_cores is not None:
                headroom = record.quota_cores - len(pinned)
                print(f"{headroom:.1f} cores of the quota beside them (reserve {server_reserve_cores():g})")
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
            print(append_pinning(arguments.directory, current_pinning()))


if __name__ == "__main__":
    main()
