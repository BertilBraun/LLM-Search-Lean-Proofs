"""Arms compared on probe runs by the follow-up's pre-set rule (src/lean_search/rl/arm_comparison.py; DESIGN.md,
"Follow-up study: controlled arms", "Evaluation").

    python experiments/probe_compare.py pair --x probe_A_phase16_run1 probe_A_phase16_run2 --x-label A \
        --y probe_B2_phase16_run1 probe_B2_phase16_run2 --y-label B2 --primary [--across-search-modes] [--seed 0]
    python experiments/probe_compare.py seeds --x <A seed 1 runs> --x-second <A seed 2 runs> --x-label A \
        --y <B2 seed 1 runs> --y-second <B2 seed 2 runs> --y-label B2
    python experiments/probe_compare.py against --reference probe_v0_run1 probe_v0_run2 \
        --variant step2_A_5e-5 probe_step2_A_5e-5 --variant step2_B2_1e-4 probe_step2_B2_1e-4
    python experiments/probe_compare.py load probe_step1_run1_v0_value_v0 [<run> ...]

A run is a probe_evaluate.py run directory (a bare name is looked up under $LEAN_SEARCH_RUNS/probe_evaluations);
only accepted runs are compared. Each side is one checkpoint in one or two runs of one identity, pooled per statement;
the comparison is on the statements every run searched. pair prints solved shares, the paired difference with its
stratified 95% interval in total and per stratum, McNemar on every pair of single runs, each two-run side's run 1
against its run 2, solved within 1-16 expansions, which limit ended each run's searches and the rule's verdict:
"primary" only with --primary (final checkpoints, two runs per side, refused otherwise), else "descriptive". seeds
prints the second-seed confirmation; against one row per variant against the reference (v0). Runs with another probe
set, expansion, token or depth budget, wall cap or concurrency are refused, and so are runs with another search config
unless --across-search-modes (step 1's reasoning comparison, the value-free search). pair
--descriptive-across-settings compares runs of other budgets, caps or search configs (e.g. depth weights) on the same
probe, descriptively: the numbers are printed, and that no verdict applies.

pair and against also print Lean's load on each run's searches, in total and per stratum: the per-tactic wall-clock
timeouts (and the statements with one), the REPL failures and the Lean seconds per policy attempt (rl/lean_load.py).
The 60 s backstop changes outcomes (an automation tactic is dropped for the rest of a search after one), so unlike
figures mean the two sides ran under unlike load. load prints the same for any run directories from their
results.jsonl, finished, accepted or not (a run still in progress included).
"""

import argparse
import json
import os
from pathlib import Path

from lean_search.rl.arm_comparison import (
    CONFIRMATION_NOTE,
    Arm,
    ArmComparison,
    Difference,
    against_reference,
    compare_arms,
    confirm_with_seeds,
    multiple_comparisons_note,
    read_arm_run,
)
from lean_search.rl.evaluation import EvaluationPaths
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.lean_load import LOAD_HEADER, LeanLoad, lean_loads, load_cell
from lean_search.search import read_results
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
EVALUATIONS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "probe_evaluations"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--seed", type=int, default=0, help="the bootstrap's")
    shared.add_argument("--across-search-modes", action="store_true", help="allow different search configs")
    labels = argparse.ArgumentParser(add_help=False)
    labels.add_argument("--x-label", default="", help="default: the checkpoint's arm and phase")
    labels.add_argument("--y-label", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", parents=[shared, labels])
    pair.add_argument("--x", nargs="+", required=True)
    pair.add_argument("--y", nargs="+", required=True)
    pair.add_argument("--primary", action="store_true", help="final checkpoints, two runs each: the primary endpoint")
    pair.add_argument(
        "--descriptive-across-settings",
        action="store_true",
        help="allow other budgets, caps or search configs (depth weights); prints that no verdict applies",
    )
    seeds = commands.add_parser("seeds", parents=[shared, labels])
    for side in ("--x", "--x-second", "--y", "--y-second"):
        seeds.add_argument(side, nargs="+", required=True)
    against = commands.add_parser("against", parents=[shared])
    against.add_argument("--reference", nargs="+", required=True)
    against.add_argument(
        "--variant", nargs="+", action="append", required=True, metavar="LABEL RUN", help="a label, then its runs"
    )
    commands.add_parser("load").add_argument("runs", nargs="+")
    return parser.parse_args()


def run_directory(run: str) -> Path:
    path = Path(run)
    return path if path.is_dir() else EVALUATIONS_DIRECTORY / (run if run.startswith("probe_") else f"probe_{run}")


def probe_strata(directory: Path) -> dict[str, str]:
    probe_set = json.loads((directory / "checkpoint.json").read_text(encoding="utf-8"))["probe_set"]
    return {statement.name: statement.stratum for statement in read_fixed_set(DATA_DIRECTORY / probe_set)}


def read_arm(runs: list[str], label: str = "") -> Arm:
    directories = [run_directory(run) for run in runs]
    strata = probe_strata(directories[0])
    arm_runs = tuple(read_arm_run(directory, strata) for directory in directories)
    return Arm(label or "/".join(arm_runs[0].identity.split("/")[:2]), arm_runs)


def run_load(run: str) -> tuple[LeanLoad, ...]:
    directory = run_directory(run)
    return lean_loads(read_results(EvaluationPaths(directory).results), probe_strata(directory))


def print_load(runs: list[str]) -> None:
    """One row per stratum, one column per run."""
    loads = [run_load(run) for run in runs]
    strata = list(dict.fromkeys(load.stratum for run in loads for load in run))
    cells = [{load.stratum: load_cell(load) for load in run} for run in loads]
    rows = [[stratum, *(run.get(stratum, "") for run in cells)] for stratum in strata]
    print(markdown_table([f"Lean load: {LOAD_HEADER}", *(run_directory(run).name for run in runs)], rows))
    print()


def points(value: float) -> str:
    return f"{100 * value:+.1f}"


def interval_text(found: Difference) -> str:
    return f"{points(found.difference)} [{points(found.lower)}, {points(found.upper)}]"


def difference_cells(found: Difference) -> list[str]:
    return [str(found.statements), f"{found.x_solved:.1%}", f"{found.y_solved:.1%}", interval_text(found)]


def print_comparison(comparison: ArmComparison, runs: list[str]) -> None:
    x, y = comparison.x, comparison.y
    rows = [
        ["all", *difference_cells(comparison.overall)],
        *([item.stratum, *difference_cells(item.difference)] for item in comparison.strata),
    ]
    print(markdown_table(["stratum", "statements", x, y, f"{x} - {y}, points [95%]"], rows))
    print()
    rows = [[item.x_run, item.y_run, item.x_only, item.y_only, f"{item.p_value:.3g}"] for item in comparison.mcnemar]
    print(markdown_table(["x run", "y run", "x only", "y only", "exact McNemar p"], rows))
    if comparison.repeats:
        print()
        rows = [
            [repeat.arm, interval_text(repeat.difference), f"{repeat.mcnemar.p_value:.3g}"]
            + ["a run-level shift: read the pooled verdict with care" if repeat.difference.excludes_zero else ""]
            for repeat in comparison.repeats
        ]
        print(markdown_table(["arm", "run 1 - run 2, points [95%]", "exact McNemar p", ""], rows))
    print()
    rows = [[item.budget, f"{item.x_solved:.1%}", f"{item.y_solved:.1%}"] for item in comparison.within]
    print(markdown_table(["solved within expansions (secondary)", x, y], rows))
    print()
    rows = [
        [ends.run, ", ".join(f"{end} {count}" for end, count in ends.counts), f"{ends.mean_generated_tokens:,.0f}"]
        for ends in comparison.ends
    ]
    print(markdown_table(["run", "what ended its searches", "generated tokens per statement"], rows))
    print()
    print_load(runs)
    print(f"Verdict: {comparison.verdict.text}")
    print(CONFIRMATION_NOTE)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "pair":
            x, y = read_arm(arguments.x, arguments.x_label), read_arm(arguments.y, arguments.y_label)
            comparison = compare_arms(
                x,
                y,
                arguments.seed,
                arguments.across_search_modes,
                arguments.primary,
                arguments.descriptive_across_settings,
            )
            print_comparison(comparison, [*arguments.x, *arguments.y])
        case "seeds":
            x = (read_arm(arguments.x), read_arm(arguments.x_second))
            y = (read_arm(arguments.y), read_arm(arguments.y_second))
            x_label, y_label = arguments.x_label or x[0].label, arguments.y_label or y[0].label
            confirmation = confirm_with_seeds(x, y, x_label, y_label, arguments.seed, arguments.across_search_modes)
            rows = [
                [f"{x_label} seed {pair.x_seed}", f"{y_label} seed {pair.y_seed}", points(pair.difference)]
                + [pair.x_ahead, pair.y_ahead, f"{pair.p_value:.3g}"]
                for pair in confirmation.pairs
            ]
            print(markdown_table(["", "", "x - y, points", "x ahead", "y ahead", "exact McNemar p"], rows))
            print(
                f"\nSeeds pooled: {interval_text(confirmation.claimed)} points; seed gaps "
                f"{100 * confirmation.x_seed_gap:.1f} ({x_label}) and {100 * confirmation.y_seed_gap:.1f} ({y_label})."
            )
            if confirmation.confirmed:
                print(f"Verdict: confirmed, {confirmation.ahead} ahead")
            else:
                print(f"Verdict: not confirmed ({'; '.join(confirmation.reasons)})")
            print(CONFIRMATION_NOTE)
        case "against":
            reference = read_arm(arguments.reference)
            variants = [read_arm(runs, label) for label, *runs in arguments.variant]
            found = against_reference(reference, variants, arguments.seed, arguments.across_search_modes)
            rows = [
                [row.label, row.runs, row.comparison.overall.statements, f"{row.comparison.overall.x_solved:.1%}"]
                + [interval_text(row.comparison.overall), row.verdict]
                for row in found
            ]
            headers = ["variant", "runs", "statements", "solved", f"minus {reference.label}, points [95%]", "verdict"]
            print(markdown_table(headers, rows))
            print(f"\n{reference.label}: {found[0].comparison.overall.y_solved:.1%} solved")
            print(multiple_comparisons_note(len(found)))
            print()
            print_load([*arguments.reference, *(run for _, *runs in arguments.variant for run in runs)])
        case "load":
            print_load(arguments.runs)


if __name__ == "__main__":
    main()
