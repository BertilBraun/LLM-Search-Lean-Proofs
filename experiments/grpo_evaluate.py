"""One fixed-target evaluation of a GRPO loop's published version, written to the loop's dashboard.

    python experiments/grpo_evaluate.py --loop-directory $LEAN_SEARCH_RUNS/<loop> --target probe [--phase 12]
    python experiments/grpo_evaluate.py --loop-directory ... --target probe --repeat 1    # a second, independent run
    python experiments/grpo_evaluate.py --loop-directory ... --target minif2f
    python experiments/grpo_evaluate.py --loop-directory ... --target held_out_states

Targets (src/lean_search/rl/fixed_targets.py, budgets in the loop config's [evaluation]): `probe` (the held-out pool
statements of grpo_fixed_sets.py select, 16 expansions, a 1-hour emergency cap per problem), `minif2f` (miniF2F-valid at
the full budget, 64 expansions) and `held_out_states` (per-sample success on the 512 held-out states, one request each).
The servers must serve the loop's current version: the running loop calls this inside its phase pauses (searches
paused, GPUs free); without a running loop (before the first phase, after the last) run it directly.
Results go to $LEAN_SEARCH_RUNS/<loop>/evaluations/<target>_v<version>/ (resumable: rerun the same command), the
fixed_targets line to the loop's metrics and a line to evaluations.jsonl. `--repeat k` searches the same version again
into <target>_v<version>_repeat<k>/ and compares it with the first run (comparison.json, the fixed_targets line).
"""

import argparse
import asyncio
import datetime
import os
from pathlib import Path

from lean_search.expert_iteration.serving import read_current, read_versions
from lean_search.monitoring.store import LoopContext, MetricsWriter
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    RepeatComparison,
    compare_repeats,
    fixed_targets_record,
)
from lean_search.rl.fixed_targets import evaluate_target
from lean_search.rl.loop import GrpoLoopPaths, read_progress, value_version
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.renaming import load_renamings
from lean_search.rl.search_models import served_run_config
from lean_search.search import load_run_config, read_results
from lean_search.search.records import to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop-directory", type=Path, required=True)
    parser.add_argument("--target", type=EvaluationKind, choices=list(EvaluationKind), required=True)
    parser.add_argument("--phase", type=int, help="the metrics line's phase (default: the last finished one)")
    parser.add_argument(
        "--repeat", type=int, default=0, help="k > 0: another run of the version, compared with the first"
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


async def evaluate(arguments: argparse.Namespace) -> None:
    config = load_loop_config(arguments.loop_directory / "loop.toml")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.name)
    current = read_current(paths.models)
    versions = (current.version, value_version(read_versions(paths.models)))
    phase = arguments.phase if arguments.phase is not None else read_progress(paths.progress).phase - 1
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / config.sampling.search_config), config.serving)
    renamings = load_renamings(config.renaming, DATA_DIRECTORY)
    directory = paths.evaluation_directory(arguments.target, current.version, arguments.repeat)
    directory.mkdir(parents=True, exist_ok=True)
    log(f"{arguments.target} of version {current.version} (value version {versions[1]}) into {directory}")
    summary = await evaluate_target(
        arguments.target,
        config.evaluation,
        template,
        directory,
        versions,
        DATA_DIRECTORY,
        RUNS_DIRECTORY,
        renamings,
        log,
    )
    comparison = None
    if arguments.repeat and arguments.target != EvaluationKind.HELD_OUT_STATES:
        first = EvaluationPaths(paths.evaluation_directory(arguments.target, current.version))
        comparison = compare_repeats(read_results(first.results), read_results(EvaluationPaths(directory).results))
        EvaluationPaths(directory).comparison.write_text(to_json(comparison), encoding="utf-8")
        log(repeat_text(comparison))
    context = LoopContext(phase=phase, policy_version=versions[0], value_version=versions[1])
    MetricsWriter(paths.directory, context).write(fixed_targets_record(summary, comparison))
    with (paths.directory / "evaluations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(to_json(summary) + "\n")
    log(
        f"{summary.solved}/{summary.problems} in {summary.wall_seconds / 60:.1f} min ({summary.expansions} expansions, "
        f"{summary.wall_clock_stops} searches stopped on the wall clock)"
    )


def repeat_text(comparison: RepeatComparison) -> str:
    return (
        f"Against the first run: {comparison.first_solved} -> {comparison.second_solved} solved of "
        f"{comparison.problems} (difference {comparison.difference:+d}; {comparison.only_first} solved only by the "
        f"first, {comparison.only_second} only by this one)"
    )


def main() -> None:
    asyncio.run(evaluate(parse_arguments()))


if __name__ == "__main__":
    main()
