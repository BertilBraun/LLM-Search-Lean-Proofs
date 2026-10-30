"""Search variants on the held-out states, beside the running loop: the error-feedback round, the failed automation in
the prompt, name repair and lower temperatures against the loop's own search (src/lean_search/rl/search_variants.py).

    python experiments/search_variants.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1
    python experiments/search_variants.py --loop-directory ... --variants baseline feedback --states 128
    python experiments/search_variants.py --loop-directory ... --report      # the comparison only

Each variant runs the loop's held-out evaluation (the loop's search template on its [serving] servers, one policy
request per state, the target's 120 s cap and REPLs; `--concurrency` overrides them) with the variant's settings from
experiments/configs/grpo/search_variants.toml. Run it right after a phase pause: the servers serve the loop's current
version, and every variant of one invocation must see the same one, so the version is read before each variant and
before each tree is written, and the run stops when it changed (a phase published a new one). Results go to
$LEAN_SEARCH_RUNS/<name>/v<version>/<variant>/ (trees/, run_config.toml, states.jsonl, summary.json), resumable per
variant (rerun the same command: states with a tree are read back); comparison.json and comparison.md beside them pair
every variant with the baseline on the states both searched.
"""

import argparse
import asyncio
import dataclasses
import datetime
import json
import os
import time
from pathlib import Path

from lean_search.expert_iteration.serving import read_current, write_json_atomically
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.loop import GrpoLoopPaths
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.search_models import run_config_text, served_run_config
from lean_search.rl.search_variants import (
    PairedComparison,
    SearchVariantsConfig,
    StateResult,
    VariantComparison,
    VariantSummary,
    comparison_table,
    error_table,
    load_search_variants_config,
    paired_comparison,
    state_results,
    variant_run_config,
    variant_summary,
)
from lean_search.rl.single_step import StateProblem, search_states, state_problem
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
DEFAULT_CONFIG = REPOSITORY_DIRECTORY / "experiments" / "configs" / "grpo" / "search_variants.toml"


class ServedVersionChangedError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Experiment:
    config: SearchVariantsConfig
    loop: GrpoLoopConfig
    paths: GrpoLoopPaths
    # The loop's version the servers serve: every variant of the invocation runs on it.
    version: int
    directory: Path
    concurrency: int


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--variants", nargs="+", help="variants to run, in the config's order (default: all)")
    parser.add_argument("--states", type=int, default=0, help="only this many states (default: all)")
    parser.add_argument("--first-state", type=int, default=0, help="the first state's index in the states file")
    parser.add_argument("--concurrency", type=int, default=0, help="REPLs in place of the target's (default: those)")
    parser.add_argument("--report", action="store_true", help="only compare the variants already run")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def selected_variants(config: SearchVariantsConfig, names: list[str] | None) -> list[str]:
    known = [variant.name for variant in config.variants]
    if names is None:
        return known
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise SystemExit(f"Unknown variants {unknown}; the config has {known}.")
    return [name for name in known if name in names]


def read_state_results(path: Path) -> list[StateResult]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(StateResult, json.loads(line)) for line in lines if line.strip()]


def write_state_results(path: Path, results: list[StateResult]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(to_json(result) + "\n" for result in results), encoding="utf-8")
    temporary.replace(path)


def read_variant_summary(path: Path) -> VariantSummary:
    return from_json_object(VariantSummary, json.loads(path.read_text(encoding="utf-8")))


async def run_variant(experiment: Experiment, name: str, states: list[StateProblem]) -> None:
    def ensure_version() -> None:
        served = read_current(experiment.paths.models).version
        if served != experiment.version:
            raise ServedVersionChangedError(
                f"The loop now serves version {served}; this run started on {experiment.version}."
            )

    ensure_version()
    loop = experiment.loop
    target = loop.evaluation.held_out_states
    if experiment.concurrency:
        target = dataclasses.replace(target, concurrency=experiment.concurrency)
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / loop.sampling.search_config), loop.serving)
    run_config = variant_run_config(template, experiment.config.variant(name), target)
    directory = experiment.directory / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run_config.toml").write_text(run_config_text(run_config), encoding="utf-8")
    log(f"{name}: {len(states)} states on version {experiment.version} into {directory}")
    started = time.monotonic()
    records = await search_states(states, run_config, directory / "trees", log, ensure_version)
    results = state_results(states, records)
    write_state_results(directory / "states.jsonl", results)
    summary_path = directory / "summary.json"
    earlier = read_variant_summary(summary_path).run_wall_seconds if summary_path.exists() else 0.0
    elapsed = earlier + time.monotonic() - started
    summary = variant_summary(name, experiment.version, run_config.policy.temperature, results, elapsed)
    write_json_atomically(summary_path, summary)
    log(
        f"{name}: success {summary.success_rate:.3f} (first round {summary.first_round_success_rate:.3f}), valid "
        f"{summary.valid_rate:.3f}, {summary.mean_children:.2f} children, {summary.mean_generated_tokens:.0f} tokens "
        f"and {summary.mean_wall_seconds:.1f} s per state"
    )


def compare(config: SearchVariantsConfig, directory: Path) -> None:
    """Every variant of the version directory with results, each paired with the baseline on their common states."""
    results: dict[str, list[StateResult]] = {}
    summaries: list[VariantSummary] = []
    for variant in config.variants:
        variant_directory = directory / variant.name
        if (variant_directory / "summary.json").exists():
            results[variant.name] = read_state_results(variant_directory / "states.jsonl")
            summaries.append(read_variant_summary(variant_directory / "summary.json"))
    paired: list[PairedComparison] = []
    if config.baseline in results:
        paired = [
            paired_comparison(
                name,
                config.baseline,
                variant_results,
                results[config.baseline],
                config.bootstrap_samples,
                config.confidence,
                config.seed,
            )
            for name, variant_results in results.items()
            if name != config.baseline
        ]
    comparison = VariantComparison(tuple(summaries), tuple(paired))
    write_json_atomically(directory / "comparison.json", comparison)
    text = comparison_table(comparison) + "\nShares of each variant's samples:\n\n" + error_table(summaries)
    (directory / "comparison.md").write_text(text, encoding="utf-8")
    print(text, flush=True)


async def main_async(arguments: argparse.Namespace) -> None:
    config = load_search_variants_config(arguments.config)
    names = selected_variants(config, arguments.variants)
    loop = load_loop_config(arguments.loop_directory / "loop.toml")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, loop.name)
    version = read_current(paths.models).version
    directory = RUNS_DIRECTORY / config.name / f"v{version}"
    experiment = Experiment(config, loop, paths, version, directory, arguments.concurrency)
    if not arguments.report:
        states = [
            state_problem(state)
            for state in read_records(RUNS_DIRECTORY / loop.evaluation.held_out_states_file, ReasoningState)
        ]
        end = arguments.first_state + arguments.states if arguments.states else len(states)
        states = states[arguments.first_state : end]
        for name in names:
            try:
                await run_variant(experiment, name, states)
            except ServedVersionChangedError as error:
                raise SystemExit(f"{error} Rerun after the next pause: it starts a new version directory.") from error
    compare(config, directory)


def main() -> None:
    asyncio.run(main_async(parse_arguments()))


if __name__ == "__main__":
    main()
