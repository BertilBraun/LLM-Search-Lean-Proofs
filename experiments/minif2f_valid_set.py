"""miniF2F-valid (data/minif2f/minif2f.jsonl, its valid split; the test split is never searched) as a fixed set that
experiments/probe_evaluate.py reads (src/lean_search/rl/fixed_sets.py, minif2f_valid_set), strata by competition.

    python experiments/minif2f_valid_set.py [--output grpo/fixed_sets/minif2f_valid.jsonl]

The output is under $LEAN_SEARCH_DATA. An existing file with the same statements is kept, one with others is refused.
"""

import argparse
import os
from collections import Counter
from pathlib import Path

from lean_search.data import Split, load_minif2f
from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.rl.fixed_sets import minif2f_valid_set, read_fixed_set, write_fixed_set

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="grpo/fixed_sets/minif2f_valid.jsonl", help="under $LEAN_SEARCH_DATA")
    return parser.parse_args()


def main() -> None:
    output = DATA_DIRECTORY / parse_arguments().output
    statements = minif2f_valid_set(load_minif2f(Split.VALID))
    if output.exists():
        if read_fixed_set(output) != statements:
            raise SystemExit(f"{output} exists with other statements: a fixed set is never replaced.")
        print(f"{output} holds miniF2F-valid already")
    else:
        write_fixed_set(output, statements)
    strata = Counter(statement.stratum for statement in statements)
    print(f"{len(statements)} statements {dict(strata)} -> {output} (sha256 {file_sha256(output)})")


if __name__ == "__main__":
    main()
