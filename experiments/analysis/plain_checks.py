"""How many verified proofs of a run's trees need the nlinarith variant: their written text fails the plain Mathlib
check (`Node.plain_verified`, recorded for every verified proof of a search with `[search] nlinarith_variant`).

    python experiments/analysis/plain_checks.py <trees directory> [...]

A directory is searched for `*.json.gz` trees at any depth (a loop's `trees/phase_NNNN/`, a probe run's `trees/`).
Prints the counts per directory and over all.
"""

import argparse
from pathlib import Path

from lean_search.rl.phase_metrics import PlainChecks, plain_checks
from lean_search.search import read_tree


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directories", type=Path, nargs="+")
    return parser.parse_args()


def directory_checks(directory: Path) -> PlainChecks:
    return plain_checks([read_tree(path, texts=False) for path in sorted(directory.rglob("*.json.gz"))])


def main() -> None:
    totals = PlainChecks(0, 0, 0)
    for directory in parse_arguments().directories:
        checks = directory_checks(directory)
        print(f"{directory}: {checks.text()}")
        totals = PlainChecks(
            totals.checked_proofs + checks.checked_proofs,
            totals.failed_proofs + checks.failed_proofs,
            totals.variant_only_trees + checks.variant_only_trees,
        )
    print(f"all: {totals.text()}")


if __name__ == "__main__":
    main()
