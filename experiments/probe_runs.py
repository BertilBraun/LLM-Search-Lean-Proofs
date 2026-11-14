"""The steps deployment/probe_runs.sh takes over its run lists (src/lean_search/rl/probe_run_list.py).

    python experiments/probe_runs.py check --concurrency 56 <run list.toml> ...   # prints the servers' loop config
    python experiments/probe_runs.py next <run list.toml> ...     # the next run's probe_evaluate.py arguments
    python experiments/probe_runs.py record <run list.toml> ...   # ledger lines for the runs finished since

check refuses (exit 1, every reason on stderr) a run with a placeholder in its settings, its evaluation config or its
search config, a probe concurrency other than --concurrency, runs on more than one loop config's servers, a held
serving lock and a running loop. next prints the arguments of the first run in interleaved order that is not accepted,
NUL-separated, or nothing when all are; a rejected run stops it (exit 3). record appends each finished run's line to
<output>/ledger.tsv beside the runs, once.
"""

import argparse
import os
import sys
from pathlib import Path

from lean_search.policy.serving_lock import lock_holder, serving_lock_path
from lean_search.rl.probe_evaluation import running_loops
from lean_search.rl.probe_run_list import (
    RunState,
    interleaved,
    loop_configs,
    planned_directory,
    probe_arguments,
    read_run_list,
    record_finished,
    run_refusals,
    run_state,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
REJECTED_EXIT_STATUS = 3


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--concurrency", type=int, required=True, help="the study's one probe concurrency")
    check.add_argument("lists", nargs="+", type=Path)
    for name in ("next", "record"):
        commands.add_parser(name).add_argument("lists", nargs="+", type=Path)
    return parser.parse_args()


def check(lists: list[Path], concurrency: int) -> None:
    runs = interleaved([read_run_list(path) for path in lists])
    refusals = [refusal for run in runs for refusal in run_refusals(run, REPOSITORY_DIRECTORY, concurrency)]
    configs = loop_configs(runs, REPOSITORY_DIRECTORY) if not refusals else []
    if len(configs) > 1:
        refusals.append(f"The runs search on several loop configs' servers: {configs}")
    holder = lock_holder(serving_lock_path(CHECKPOINTS_DIRECTORY))
    if holder is not None:
        refusals.append(f"Process {holder} holds the serving lock: something else uses the servers.")
    activity = running_loops(RUNS_DIRECTORY)
    refusals += [f"A loop runs: {loop}" for loop in activity.running]
    if refusals:
        print("\n".join(refusals), file=sys.stderr)
        raise SystemExit(1)
    print(configs[0])


def next_run(lists: list[Path]) -> int:
    for run in interleaved([read_run_list(path) for path in lists]):
        directory = planned_directory(run, RUNS_DIRECTORY, REPOSITORY_DIRECTORY)
        match run_state(directory):
            case RunState.ACCEPTED:
                continue
            case RunState.REJECTED:
                print(
                    f"{run.name} was rejected ({directory}/run.json: too many wall-clock stops). Repeat it under "
                    "another name with the wall cap doubled, and every run it is compared with at that cap; then take "
                    "it out of the list.",
                    file=sys.stderr,
                )
                return REJECTED_EXIT_STATUS
            case RunState.PENDING:
                sys.stdout.write("\0".join(probe_arguments(run)) + "\0")
                return 0
    return 0


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "check":
            check(arguments.lists, arguments.concurrency)
        case "next":
            raise SystemExit(next_run(arguments.lists))
        case "record":
            runs = interleaved([read_run_list(path) for path in arguments.lists])
            for line in record_finished(runs, RUNS_DIRECTORY, REPOSITORY_DIRECTORY):
                print(f"Ledger: {line.text.rstrip()}")


if __name__ == "__main__":
    main()
