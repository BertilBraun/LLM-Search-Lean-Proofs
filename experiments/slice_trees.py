"""A run's trees cut into slices of equal generated tokens by finish order (src/lean_search/rl/tree_slices.py;
DESIGN.md, "Follow-up study: controlled arms", "Step 2").

    python experiments/slice_trees.py --trees $LEAN_SEARCH_RUNS/followup_shared_sampling/trees --slices 1 \
        --output $LEAN_SEARCH_RUNS/followup_shared_sampling/slices

Reads the run's tree index (trees/index.jsonl, every tree of every phase directory) and writes output/slice_k/ (links
to the tree files and the slice's index.jsonl), one per slice, and output/manifest.json: per slice its trees, generated
tokens, solved share, difficulty range, statements per character band, below-band share and statements seen in an
earlier slice. A slice directory is what `grpo_phase.py --trees` and the expert-iteration builder's tree_directories
take. Step 2 (deployment/study_chain.sh) uses --slices 1: its shared phase's trees, which the run keeps under a phase
directory, linked into one directory, slice_1, that arm A's learning-rate rounds train on. Refuses while the run's loop
is running, when the index changes while being read, and an existing output.
"""

import argparse
from pathlib import Path

from lean_search.rl.probe_evaluation import running_loops
from lean_search.rl.tree_slices import slice_by_tokens, write_slices
from lean_search.rl.tree_store import INDEX_FILE, TreeStore
from lean_search.search.summary import markdown_table


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", type=Path, required=True, help="a loop's trees directory (with index.jsonl)")
    parser.add_argument("--slices", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def loop_running(run_directory: Path) -> bool:
    """The run's loop process (loop.pid) or a job it started still runs."""
    entries = running_loops(run_directory.parent).running
    return any(entry.startswith((f"{run_directory.name} ", f"{run_directory.name}'s ")) for entry in entries)


def main() -> None:
    arguments = parse_arguments()
    trees = arguments.trees.resolve()
    if loop_running(trees.parent):
        raise SystemExit(f"The loop of {trees.parent} still runs: stop it before cutting its trees.")
    index = trees / INDEX_FILE
    before = index.read_bytes()
    entries = TreeStore(trees).entries
    if not entries:
        raise SystemExit(f"No tree index entries under {trees}.")
    slices = slice_by_tokens(entries, arguments.slices)
    if index.read_bytes() != before:
        raise SystemExit(f"{index} changed while it was read: a loop still writes there.")
    manifest = write_slices(trees, slices, arguments.output, len(before.splitlines()))
    rows = [
        [
            record.slice,
            record.trees,
            f"{record.generated_tokens:,}",
            f"{record.solved_share:.1%}",
            f"{record.difficulty_low}-{record.difficulty_high}",
            f"{record.below_band_share:.1%}",
            record.statements_seen_before,
            ", ".join(f"{count.band}: {count.trees}" for count in record.by_character_band),
        ]
        for record in manifest.slices
    ]
    headers = ["slice", "trees", "tokens", "solved", "difficulty", "below band", "seen before", "by proof characters"]
    print(markdown_table(headers, rows))
    print(f"{manifest.trees} trees, {manifest.generated_tokens:,} generated tokens; {arguments.output}/manifest.json")


if __name__ == "__main__":
    main()
