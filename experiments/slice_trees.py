"""Step 2's shared trees cut into slices of equal generated tokens by finish order (src/lean_search/rl/tree_slices.py;
DESIGN.md, "Follow-up study: controlled arms", "Step 2").

    python experiments/slice_trees.py --trees $LEAN_SEARCH_RUNS/<shared run>/trees --slices 4 \
        --output $LEAN_SEARCH_RUNS/<shared run>/slices

Reads the run's tree index (trees/index.jsonl, every tree of every phase directory) and writes output/slice_k/ (links
to the tree files and the slice's index.jsonl), one per slice, and output/manifest.json: per slice its trees, generated
tokens and solved share. A slice directory is what `grpo_phase.py --trees` and the expert-iteration builder take,
e.g. --trees <output>/slice_4 for one slice, or slice_1 ... slice_4 for four. Refuses an existing output.
"""

import argparse
from pathlib import Path

from lean_search.rl.tree_slices import slice_by_tokens, write_slices
from lean_search.rl.tree_store import TreeStore
from lean_search.search.summary import markdown_table


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", type=Path, required=True, help="a loop's trees directory (with index.jsonl)")
    parser.add_argument("--slices", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    entries = TreeStore(arguments.trees).entries
    if not entries:
        raise SystemExit(f"No tree index entries under {arguments.trees}.")
    manifest = write_slices(arguments.trees, slice_by_tokens(entries, arguments.slices), arguments.output)
    rows = [
        [record.slice, record.trees, f"{record.generated_tokens:,}", f"{record.solved_share:.1%}", record.directory]
        for record in manifest.slices
    ]
    print(markdown_table(["slice", "trees", "generated tokens", "solved", "directory"], rows))
    print(f"{manifest.trees} trees, {manifest.generated_tokens:,} generated tokens; {arguments.output}/manifest.json")


if __name__ == "__main__":
    main()
