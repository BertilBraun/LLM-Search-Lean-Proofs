"""One fixed-target evaluation of a GRPO loop's published version, written to the loop's dashboard.

    python experiments/grpo_evaluate.py --loop-directory $LEAN_SEARCH_RUNS/<loop> --target probe [--phase 12]
    python experiments/grpo_evaluate.py --loop-directory ... --target probe --repeat 1    # a second, independent run
    python experiments/grpo_evaluate.py --loop-directory ... --target minif2f
    python experiments/grpo_evaluate.py --loop-directory ... --target held_out_states
    python experiments/grpo_evaluate.py --loop-directory ... --target value_ab --value-model initial    # then published

Targets (src/lean_search/rl/fixed_targets.py, budgets in the loop config's [evaluation]): `probe` (the held-out pool
statements of grpo_fixed_sets.py select, 16 expansions, a 1-hour emergency cap per problem), `minif2f` (miniF2F-valid at
the full budget, 64 expansions), `held_out_states` (per-sample success on the 512 held-out states, one request each) and
`value_ab` (the value A/B search: part of the probe set, once with each value model).
The servers must serve the loop's current policy and the value model named by --value-model (default: the loop
config's `evaluation.value_model`, value v0 unless changed, so the probe and miniF2F measure the policy alone): the
running loop serves them and calls this inside its phase pauses (searches paused, GPUs free); without a running loop
(before the first phase, after the last) serve them and run it directly.
Results go to $LEAN_SEARCH_RUNS/<loop>/evaluations/<target>_v<version>/ (resumable: rerun the same command), the
fixed_targets line to the loop's metrics and a line to evaluations.jsonl. `--repeat k` searches the same version again
into <target>_v<version>_repeat<k>/ and compares it with the first run (comparison.json, the fixed_targets line). The
value A/B's arms go to value_ab_v<version>_<value model>/; the published arm, run after the initial one, compares
the two per problem (comparison.json, the value_ab line).
"""

import argparse
import asyncio
import dataclasses
import datetime
import os
from pathlib import Path

from lean_search.expert_iteration.serving import read_current, read_versions
from lean_search.monitoring.families import ValueAbResult
from lean_search.monitoring.store import LoopContext, MetricsWriter
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    EvaluationSummary,
    RepeatComparison,
    compare_repeats,
    fixed_targets_record,
    value_ab_result,
)
from lean_search.rl.fixed_targets import evaluate_target
from lean_search.rl.loop import (
    GrpoLoopPaths,
    earlier_value_ab_results,
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
    parser.add_argument(
        "--repeat", type=int, default=0, help="k > 0: another run of the version, compared with the first"
    )
    parser.add_argument(
        "--value-model",
        type=EvaluationValueModel,
        choices=list(EvaluationValueModel),
        help="the value model the servers serve (default: the loop config's evaluation.value_model)",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def served_value_version(config: GrpoLoopConfig, paths: GrpoLoopPaths, value_model: EvaluationValueModel) -> int:
    versions = read_versions(paths.models)
    match value_model:
        case EvaluationValueModel.INITIAL:
            return value_adapter_version(versions, config.initial.value_adapter)
        case EvaluationValueModel.PUBLISHED:
            return value_version(versions)


async def evaluate(arguments: argparse.Namespace) -> None:
    config = load_loop_config(arguments.loop_directory / "loop.toml")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.name)
    current = read_current(paths.models)
    value_model = arguments.value_model or config.evaluation.value_model
    versions = (current.version, served_value_version(config, paths, value_model))
    phase = arguments.phase if arguments.phase is not None else read_progress(paths.progress).phase - 1
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / config.sampling.search_config), config.serving)
    renamings = load_renamings(config.renaming, DATA_DIRECTORY)
    arm = value_model if arguments.target == EvaluationKind.VALUE_AB else None
    directory = paths.evaluation_directory(arguments.target, current.version, arguments.repeat, arm)
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
    context = LoopContext(phase=phase, policy_version=versions[0], value_version=versions[1])
    writer = MetricsWriter(paths.directory, context)
    if arguments.target == EvaluationKind.VALUE_AB:
        if value_model == EvaluationValueModel.PUBLISHED:
            summary = compare_value_arms(config, paths, current.version, summary, directory)
            if summary.value_ab is not None:
                writer.write(summary.value_ab)
                log(value_ab_text(summary.value_ab))
    else:
        comparison = None
        if arguments.repeat and arguments.target != EvaluationKind.HELD_OUT_STATES:
            first = EvaluationPaths(paths.evaluation_directory(arguments.target, current.version))
            comparison = compare_repeats(read_results(first.results), read_results(EvaluationPaths(directory).results))
            EvaluationPaths(directory).comparison.write_text(to_json(comparison), encoding="utf-8")
            log(repeat_text(comparison))
        writer.write(fixed_targets_record(summary, comparison))
    with (paths.directory / "evaluations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(to_json(summary) + "\n")
    log(
        f"{summary.solved}/{summary.problems} in {summary.wall_seconds / 60:.1f} min ({summary.expansions} expansions, "
        f"{summary.wall_clock_stops} searches stopped on the wall clock)"
    )


def compare_value_arms(
    config: GrpoLoopConfig, paths: GrpoLoopPaths, version: int, summary: EvaluationSummary, directory: Path
) -> EvaluationSummary:
    """The published arm against the initial arm of the same version, once that ran; the summary then carries it."""
    reference = EvaluationPaths(
        paths.evaluation_directory(EvaluationKind.VALUE_AB, version, 0, EvaluationValueModel.INITIAL)
    )
    if not reference.summary.exists():
        log(f"No initial arm in {reference.directory} yet: nothing to compare")
        return summary
    published = EvaluationPaths(directory)
    value_versions = (served_value_version(config, paths, EvaluationValueModel.INITIAL), summary.value_version)
    result = value_ab_result(
        read_results(reference.results),
        read_results(published.results),
        config.evaluation.value_ab_test,
        value_versions,
        earlier_value_ab_results(paths, version, summary.value_version),
    )
    compared = dataclasses.replace(summary, value_ab=result)
    published.comparison.write_text(to_json(result), encoding="utf-8")
    published.summary.write_text(to_json(compared), encoding="utf-8")
    return compared


def repeat_text(comparison: RepeatComparison) -> str:
    return (
        f"Against the first run: {comparison.first_solved} -> {comparison.second_solved} solved of "
        f"{comparison.problems} (difference {comparison.difference:+d}; {comparison.only_first} solved only by the "
        f"first, {comparison.only_second} only by this one)"
    )


def value_ab_text(result: ValueAbResult) -> str:
    return (
        f"Value A/B: published v{result.published_value_version} {result.published_solved}, reference "
        f"v{result.reference_value_version} {result.reference_solved} of {result.problems} ({result.only_published} "
        f"solved by the published only, {result.only_reference} by the reference only; p = {result.p_value:.3f}); "
        f"pooled over {result.pooled_runs} A/B runs {result.pooled_only_published} vs {result.pooled_only_reference}, "
        f"p(better) = {result.better_p_value:.3f}, p(worse) = {result.worse_p_value:.3f}: "
        + ("better" if result.passed else "worse" if result.worse else "no significant difference")
    )


def main() -> None:
    asyncio.run(evaluate(parse_arguments()))


if __name__ == "__main__":
    main()
