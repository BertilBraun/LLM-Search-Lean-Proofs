"""Search variants on the held-out states, beside the running loop: the error-feedback round and its blind control,
the failed automation in the prompt and its sweep-first control, name repair and temperatures against the loop's own
search (src/lean_search/rl/search_variants.py, experiments/configs/grpo/search_variants.toml).

    python experiments/search_variants.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1
    python experiments/search_variants.py --loop-directory ... --variants baseline feedback_always --states 128
    python experiments/search_variants.py --loop-directory ... --report      # the comparison only
    python experiments/search_variants.py --loop-directory ... --report \
        --results $LEAN_SEARCH_RUNS/grpo_search_variants/v3                # an earlier run's trees

Each variant runs the loop's held-out evaluation (the loop's search template with its options off, on its [serving]
servers, one policy request per state, the target's 120 s cap) with the variant's settings. The variants run
interleaved: every variant searches a chunk of `chunk_states` states (64) before the next chunk, all from one pool of
`--concurrency` REPLs (default 40, beside the loop's own 112 searches: run it while the loop samples, not at a pause).

Run it while the loop samples. Every tree must come from the version the run started on, and from the loop's pause on
its servers may answer with the next version before the loop records it; so the loop's phase and stage
(loop_state.json) and its recorded version are read at the start and again before each tree is written, and the run
stops (the tree in flight discarded) once the loop paused. Rerun after the next phase began: the run continues in a
new version directory; within one, a rerun searches only the states without a tree (run_config.toml must match).

Results: $LEAN_SEARCH_RUNS/<name>/v<version>/<variant>/{trees/, run_config.toml}, and comparison.json and
comparison.md beside them, rebuilt from every tree present.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import os
import time
from pathlib import Path

from lean_search.expert_iteration.serving import read_current, write_json_atomically
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.loop import GrpoLoopPaths, read_progress
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.search_models import SearchModels, open_search_models, run_config_text, served_run_config
from lean_search.rl.search_variants import (
    SearchVariantsConfig,
    ServedVersion,
    VariantResults,
    compare_variants,
    comparison_text,
    interleaved_chunks,
    load_search_variants_config,
    requested_samples,
    served_version,
    state_result,
    variant_run_config,
)
from lean_search.rl.single_step import StateProblem, search_state, state_problem, state_tree_path
from lean_search.search import RunConfig, load_run_config
from lean_search.search.records import read_tree, write_tree

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
DEFAULT_CONFIG = REPOSITORY_DIRECTORY / "experiments" / "configs" / "grpo" / "search_variants.toml"
# Beside the loop's 112 searching REPLs (rl/README.md, "Host memory").
DEFAULT_CONCURRENCY = 40
RUN_CONFIG_FILE = "run_config.toml"


class ServedVersionChangedError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Variant:
    name: str
    config: RunConfig
    trees: Path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--variants", nargs="+", help="variants to run or report, in the config's order (default: all)")
    parser.add_argument("--states", type=int, default=0, help="only this many states (default: all)")
    parser.add_argument("--first-state", type=int, default=0, help="the first state's index in the states file")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="REPLs and searches at once")
    parser.add_argument("--report", action="store_true", help="only compare the variants already run")
    parser.add_argument("--results", type=Path, help="the version directory to report (default: the served one's)")
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


def served_now(paths: GrpoLoopPaths) -> ServedVersion | None:
    return served_version(read_progress(paths.progress), read_current(paths.models).version)


def prepared_variant(directory: Path, name: str, config: RunConfig) -> Variant:
    """The variant's directory with its run config; a rerun must search with the config its trees were made with."""
    variant_directory = directory / name
    path = variant_directory / RUN_CONFIG_FILE
    if path.exists() and load_run_config(path) != config:
        raise SystemExit(f"{path} differs from the variant's config now; its trees came from another config.")
    variant_directory.mkdir(parents=True, exist_ok=True)
    path.write_text(run_config_text(config), encoding="utf-8")
    return Variant(name, config, variant_directory / "trees")


async def run_variants(
    variants: list[Variant], states: list[StateProblem], chunk_states: int, concurrency: int, paths: GrpoLoopPaths
) -> None:
    started_on = served_now(paths)
    assert started_on is not None

    def ensure_served() -> None:
        now = served_now(paths)
        if now != started_on:
            raise ServedVersionChangedError(f"The loop left the sampling of phase {started_on.phase}: now {now}.")

    lean = variants[0].config.lean
    async with contextlib.AsyncExitStack() as stack:
        models: dict[str, SearchModels] = {}
        for variant in variants:
            models[variant.name] = await stack.enter_async_context(open_search_models(variant.config))
        pool = await stack.enter_async_context(LeanReplPool(concurrency, LeanReplConfig(), lean.restart_fraction))
        await pool.start(sorted({state.problem.header for state in states}))
        semaphore = asyncio.Semaphore(concurrency)

        async def search_one(variant: Variant, state: StateProblem) -> None:
            async with semaphore, pool.acquire() as repl:
                record = await search_state(state, repl, models[variant.name], variant.config.search)
            ensure_served()
            await asyncio.to_thread(write_tree, state_tree_path(variant.trees, state), record)

        chunks = interleaved_chunks(states, chunk_states)
        for number, chunk in enumerate(chunks, 1):
            pending = [
                (variant, state)
                for state in chunk
                for variant in variants
                if not state_tree_path(variant.trees, state).exists()
            ]
            started = time.monotonic()
            searches = [asyncio.create_task(search_one(variant, state)) for variant, state in pending]
            try:
                await asyncio.gather(*searches)
            finally:
                # After a failure the other searches must stop before the pool closes under them.
                for search in searches:
                    search.cancel()
                await asyncio.gather(*searches, return_exceptions=True)
            log(f"Chunk {number}/{len(chunks)}: {len(pending)} searches in {time.monotonic() - started:.0f} s")


def held_out_states(loop: GrpoLoopConfig) -> list[StateProblem]:
    return [
        state_problem(state)
        for state in read_records(RUNS_DIRECTORY / loop.evaluation.held_out_states_file, ReasoningState)
    ]


def report(config: SearchVariantsConfig, directory: Path, states: list[StateProblem], names: list[str] | None) -> None:
    """Every variant directory with trees (or the chosen ones), from every tree present, paired per state."""
    found = sorted(
        path.parent.name for path in directory.glob(f"*/{RUN_CONFIG_FILE}") if (path.parent / "trees").is_dir()
    )
    order = [variant.name for variant in config.variants]
    found.sort(key=lambda name: (order.index(name) if name in order else len(order), name))
    runs = []
    for name in found if names is None else [name for name in found if name in names]:
        run_config = load_run_config(directory / name / RUN_CONFIG_FILE)
        requested = requested_samples(run_config)
        trees = directory / name / "trees"
        results = tuple(
            state_result(state.problem.name, read_tree(path), state.reference_keys, requested)
            for state in states
            if (path := state_tree_path(trees, state)).exists()
        )
        runs.append(VariantResults(name, run_config, results))
        log(f"{name}: {len(results)} states read")
    comparison = compare_variants(runs, config)
    write_json_atomically(directory / "comparison.json", comparison)
    text = comparison_text(comparison)
    (directory / "comparison.md").write_text(text, encoding="utf-8")
    print(text, flush=True)


async def main_async(arguments: argparse.Namespace) -> None:
    config = load_search_variants_config(arguments.config)
    loop = load_loop_config(arguments.loop_directory / "loop.toml")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, loop.name)
    states = held_out_states(loop)
    if arguments.report:
        directory = arguments.results or RUNS_DIRECTORY / config.name / f"v{read_current(paths.models).version}"
        report(config, directory, states, arguments.variants)
        return
    served = served_now(paths)
    if served is None:
        raise SystemExit(
            "The loop is not sampling (paused, training, publishing or evaluating); start once it samples."
        )
    directory = RUNS_DIRECTORY / config.name / f"v{served.version}"
    end = arguments.first_state + arguments.states if arguments.states else len(states)
    chosen = states[arguments.first_state : end]
    target = dataclasses.replace(loop.evaluation.held_out_states, concurrency=arguments.concurrency)
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / loop.sampling.search_config), loop.serving)
    variants = [
        prepared_variant(directory, name, variant_run_config(template, config.variant(name), target))
        for name in selected_variants(config, arguments.variants)
    ]
    log(
        f"{len(variants)} variants on {len(chosen)} states, version {served.version} (phase {served.phase}): "
        f"{directory}"
    )
    try:
        await run_variants(variants, chosen, config.chunk_states, arguments.concurrency, paths)
    except ServedVersionChangedError as error:
        log(f"{error} Stopped; rerun once the next phase samples (a new version directory).")
    report(config, directory, states, None)


def main() -> None:
    asyncio.run(main_async(parse_arguments()))


if __name__ == "__main__":
    main()
