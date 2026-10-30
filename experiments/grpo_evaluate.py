"""One fixed-target evaluation of a GRPO loop's published version, written to the loop's dashboard.

    python experiments/grpo_evaluate.py --loop-directory $LEAN_SEARCH_RUNS/<loop> --target probe --slot 7 [--phase 12]
    python experiments/grpo_evaluate.py --loop-directory ... --target probe --slot 7 --repeat 1   # independent rerun
    python experiments/grpo_evaluate.py --loop-directory ... --target probe --slot 7 --value-arm  # published value
    python experiments/grpo_evaluate.py --loop-directory ... --target probe                       # the whole set
    python experiments/grpo_evaluate.py --loop-directory ... --target minif2f
    python experiments/grpo_evaluate.py --loop-directory ... --target held_out_states

Targets (src/lean_search/rl/fixed_targets.py, budgets in the loop config's [evaluation]): `probe` (the held-out pool
statements of grpo_fixed_sets.py select, 16 expansions and a per-problem wall cap; with --slot only the part
slot % probe_parts of the set, stratified like it), `minif2f` (miniF2F-valid at the full budget, 64 expansions) and
`held_out_states` (per-sample success on the 512 held-out states, one request each).
The servers must serve the loop's current policy and the loop config's `evaluation.value_model`, or for --value-arm the
published value model: the running loop serves them and calls this before sampling (version 0's baselines, all at
once), at its phase pauses (the held-out states) or beside sampling (`evaluation.beside_sampling`: the probe and
miniF2F); without a running loop (before the first phase, after the last) serve them and run it directly.
`--concurrency` overrides the target's REPLs.
Results go to $LEAN_SEARCH_RUNS/<loop>/evaluations/<target>[_slot<slot>]_v<version>/ (resumable: rerun the same
command; progress.json holds the problems still without a result), the fixed_targets line to the loop's metrics (a
probe slot's with the rolling whole set of the last probe_parts slots) and a line to evaluations.jsonl. `--repeat k`
searches the same version (and part) again into ..._repeat<k>/ and compares it with the first run (comparison.json, the
fixed_targets line), once both are complete: whichever of the two finishes last compares them. `--value-arm` searches a
slot's part with the published value model into ..._value_arm/ and pairs it per problem with the slot's run
(comparison.json, pooled with the earlier value arms; the value_arm line).
"""

import argparse
import asyncio
import dataclasses
import datetime
import os
from pathlib import Path

from lean_search.expert_iteration.serving import read_current, read_versions
from lean_search.monitoring.store import LoopContext, MetricsWriter
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    EvaluationRun,
    EvaluationSummary,
    RepeatComparison,
    RollingProbe,
    compare_repeats,
    fixed_targets_record,
    read_summary,
    repeats_to_compare,
    rolling_probe,
    value_arm_result,
    value_arm_text,
)
from lean_search.rl.fixed_targets import evaluate_target
from lean_search.rl.loop import (
    GrpoLoopPaths,
    earlier_value_arm_results,
    probe_baseline_differences,
    read_progress,
    value_adapter_version,
    value_version,
)
from lean_search.rl.loop_config import EvaluationValueModel, GrpoLoopConfig, load_loop_config
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
    parser.add_argument("--slot", type=int, help="a probe slot: only its part of the probe set")
    parser.add_argument(
        "--repeat", type=int, default=0, help="k > 0: another run of the version, compared with the first"
    )
    parser.add_argument(
        "--value-arm", action="store_true", help="the slot's part with the published value model, paired with the slot"
    )
    parser.add_argument("--concurrency", type=int, default=0, help="REPLs in place of the target's (default: those)")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def evaluation_run(arguments: argparse.Namespace) -> EvaluationRun:
    if arguments.slot is not None and arguments.target != EvaluationKind.PROBE:
        raise SystemExit("--slot is a probe slot: use it with --target probe.")
    if arguments.value_arm and (arguments.slot is None or arguments.repeat):
        raise SystemExit("--value-arm pairs a probe slot's first run: give --slot, not --repeat.")
    if arguments.concurrency < 0:
        raise SystemExit("--concurrency must be at least 1 (0: the target's).")
    return EvaluationRun(arguments.target, arguments.slot, arguments.repeat, arguments.value_arm, arguments.concurrency)


def served_value_version(config: GrpoLoopConfig, paths: GrpoLoopPaths, value_model: EvaluationValueModel) -> int:
    versions = read_versions(paths.models)
    match value_model:
        case EvaluationValueModel.INITIAL:
            return value_adapter_version(versions, config.initial.value_adapter)
        case EvaluationValueModel.PUBLISHED:
            return value_version(versions)


async def evaluate(arguments: argparse.Namespace) -> None:
    run = evaluation_run(arguments)
    config = load_loop_config(arguments.loop_directory / "loop.toml")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.name)
    current = read_current(paths.models)
    value_model = EvaluationValueModel.PUBLISHED if run.value_arm else config.evaluation.value_model
    versions = (current.version, served_value_version(config, paths, value_model))
    phase = arguments.phase if arguments.phase is not None else read_progress(paths.progress).phase - 1
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / config.sampling.search_config), config.serving)
    renamings = load_renamings(config.renaming, DATA_DIRECTORY)
    directory = paths.evaluation_directory(run, current.version)
    directory.mkdir(parents=True, exist_ok=True)
    log(f"{run} of version {current.version} (value version {versions[1]}) into {directory}")
    summary = await evaluate_target(
        run, config.evaluation, template, directory, versions, DATA_DIRECTORY, RUNS_DIRECTORY, renamings, log
    )
    context = LoopContext(phase=phase, policy_version=versions[0], value_version=versions[1])
    writer = MetricsWriter(paths.directory, context)
    if run.value_arm:
        summary = compare_value_arm(config, paths, run, current.version, summary, directory)
        assert summary.value_arm is not None
        writer.write(summary.value_arm)
        log(value_arm_text(summary.value_arm))
    elif run.kind == EvaluationKind.HELD_OUT_STATES:
        writer.write(fixed_targets_record(summary))
    else:
        first = EvaluationPaths(paths.evaluation_directory(dataclasses.replace(run, repeat=0), current.version))
        for repeat in repeats_to_compare(first, EvaluationPaths(directory), run.repeat):
            comparison = compare_repeats(read_results(first.results), read_results(repeat.results))
            repeat.comparison.write_text(to_json(comparison), encoding="utf-8")
            writer.write(fixed_targets_record(read_summary(repeat.summary), comparison))
            log(repeat_text(comparison))
        if not run.repeat:
            first_run_of_slot = run.slot is not None
            rolling = last_slots(config, paths, run.slot) if first_run_of_slot else None
            baseline = probe_baseline_differences(paths, config.evaluation, run.slot) if first_run_of_slot else None
            writer.write(fixed_targets_record(summary, None, rolling, baseline))
    with (paths.directory / "evaluations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(to_json(summary) + "\n")
    log(
        f"{summary.solved}/{summary.problems} in {summary.wall_seconds / 60:.1f} min ({summary.expansions} expansions, "
        f"{summary.wall_clock_stops} searches stopped on the wall clock)"
    )


def last_slots(config: GrpoLoopConfig, paths: GrpoLoopPaths, slot: int) -> RollingProbe | None:
    """This slot and the ones before it, each part of the probe set once, once all of them ran."""
    first = slot - config.evaluation.probe_parts + 1
    directories = [paths.probe_slot_directory(number) for number in range(first, slot + 1)] if first >= 0 else []
    if not directories or any(directory is None for directory in directories):
        return None
    return rolling_probe([read_summary(directory / "summary.json") for directory in directories if directory])


def compare_value_arm(
    config: GrpoLoopConfig,
    paths: GrpoLoopPaths,
    run: EvaluationRun,
    version: int,
    summary: EvaluationSummary,
    directory: Path,
) -> EvaluationSummary:
    """The value arm against the slot's run with the reference value model, which the loop runs first."""
    assert run.slot is not None
    reference = EvaluationPaths(paths.evaluation_directory(dataclasses.replace(run, value_arm=False), version))
    if not reference.summary.exists():
        raise SystemExit(f"No run of slot {run.slot} in {reference.directory}: run the slot before its value arm.")
    published = EvaluationPaths(directory)
    value_versions = (served_value_version(config, paths, EvaluationValueModel.INITIAL), summary.value_version)
    result = value_arm_result(
        read_results(reference.results),
        read_results(published.results),
        run.slot,
        run.slot % config.evaluation.probe_parts,
        value_versions,
        earlier_value_arm_results(paths, directory),
        config.evaluation.value_arm,
    )
    compared = dataclasses.replace(summary, value_arm=result)
    published.comparison.write_text(to_json(result), encoding="utf-8")
    published.summary.write_text(to_json(compared), encoding="utf-8")
    return compared


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
