"""The claim watch of one phase of a GRPO arm against its first (review BG, S1; src/lean_search/rl/claim_watch.py):
bare-`have` openings (every statement and below the band, from health.jsonl), the two subclasses that grew in arm A's
first run, the substitutes (`obtain`, `suffices`, `have … :=`), claims proved, the per-sample advantage of on-graph
decompositions against direct openings under the phase's own reward, mean explanation tokens, held-out against v0.
Reads the run directory only; CPU, one process by default (run it at nice 19 on the Lean CPUs beside a loop).

    PYTHONPATH=src python experiments/claim_watch.py --run /workspace/runs/followup_A --phase 2
"""

import argparse
import tomllib
import zlib
from functools import partial
from multiprocessing import Pool
from pathlib import Path

from lean_search.rl.claim_watch import (
    PhaseWatch,
    TreeWatch,
    phase_health,
    proof_band,
    tree_watch,
    version_zero_held_out,
    watch_lines,
)
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.search.records import from_json_object, read_tree


def phase_config(run: Path, phase: int) -> TrainingPhaseConfig:
    """The phase's own training config, else the latest written (a phase still sampling)."""
    configs = sorted((run / "training").glob("phase_*.toml"))
    own = run / "training" / f"phase_{phase:04d}.toml"
    if not configs:
        raise ValueError(f"{run} has no training/phase_*.toml: not a loop's run directory.")
    path = own if own.exists() else configs[-1]
    return from_json_object(TrainingPhaseConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def entry_watch(entry: TreeEntry, directory: Path, config: TrainingPhaseConfig) -> TreeWatch:
    try:
        record = read_tree(directory / entry.file)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeWatch()
    return tree_watch(record, config, proof_band(entry.difficulty))


def phase_watch(run: Path, phase: int, workers: int) -> PhaseWatch:
    store = TreeStore(run / "trees")
    entries = [entry for entry in store.phase_entries(phase) if (store.directory / entry.file).exists()]
    task = partial(entry_watch, directory=store.directory, config=phase_config(run, phase))
    total = TreeWatch()
    if workers == 1:
        for entry in entries:
            total += task(entry)
    else:
        with Pool(workers, maxtasksperchild=50) as pool:
            for found in pool.imap_unordered(task, entries, chunksize=4):
                total += found
    return PhaseWatch(phase, total, phase_health(run, phase))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True, help="the loop's run directory")
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--reference-phase", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    reference = phase_watch(arguments.run, arguments.reference_phase, arguments.workers)
    current = phase_watch(arguments.run, arguments.phase, arguments.workers)
    version_zero = version_zero_held_out(arguments.run / "evaluations.jsonl")
    print("\n".join(watch_lines(current, reference, version_zero)))


if __name__ == "__main__":
    main()
