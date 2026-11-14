"""Step 2's ranking of one signal's learning rates against v0 (src/lean_search/rl/rate_ranking.py; DESIGN.md,
"Follow-up study: controlled arms", "Step 2", "Ranking the rates").

    python experiments/rank_learning_rates.py --v0 v0 [--v0-gate step2_v0] \
        --variant A_2e-5 2e-5 step2_A_2e-5 [step2_A_2e-5] \
        --variant A_5e-5 5e-5 step2_A_5e-5 [step2_A_5e-5] \
        --variant A_1e-4 1e-4 step2_A_1e-4 [step2_A_1e-4]

A variant is a label, its learning rate, its held-out run (experiments/held_out_evaluate.py --name: a directory or a
name under $LEAN_SEARCH_RUNS/held_out_evaluations/held_out_<name>) and optionally its gate-set runs
(probe_evaluate.py with followup/gate_evaluation.toml: a directory or a name under
$LEAN_SEARCH_RUNS/gate_evaluations/probe_<name>); --v0-gate is v0's gate runs. Prints every variant against v0 (valid
Lean and success paired per held-out state, the gate set paired per statement, each with its 95% interval), then the
rule's choice. Give the gate runs for all variants or none: they cost ~1 h each (gate_evaluation.toml).
"""

import argparse
import json
import os
from pathlib import Path

from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.arm_comparison import Arm, Difference, read_arm_run
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.probe_rating import DifferenceInterval
from lean_search.rl.rate_ranking import HeldOutStates, Variant, against_v0, choose_rate
from lean_search.rl.single_step import StateProblem, sample_success, state_problem, state_tree_path
from lean_search.search import read_tree
from lean_search.search.summary import markdown_table

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
LOOP_CONFIG = "experiments/configs/grpo/followup/base.toml"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--v0", required=True, help="v0's held-out run")
    parser.add_argument("--v0-gate", nargs="+", default=[], help="v0's gate-set runs")
    parser.add_argument(
        "--variant", nargs="+", action="append", required=True, metavar="LABEL RATE HELD_OUT [GATE ...]"
    )
    parser.add_argument("--seed", type=int, default=0, help="the bootstraps'")
    return parser.parse_args()


def located(run: str, root: Path, prefix: str) -> Path:
    path = Path(run)
    return path if path.is_dir() else root / f"{prefix}{run}"


def held_out_states() -> list[StateProblem]:
    loop = load_loop_config(REPOSITORY_DIRECTORY / LOOP_CONFIG)
    records = read_records(RUNS_DIRECTORY / loop.evaluation.held_out_states_file, ReasoningState)
    return [state_problem(state) for state in records]


def read_held_out(label: str, run: str, states: list[StateProblem]) -> HeldOutStates:
    trees = located(run, RUNS_DIRECTORY / "held_out_evaluations", "held_out_") / "trees"
    paths = {state.problem.name: (state, state_tree_path(trees, state)) for state in states}
    return HeldOutStates(
        label,
        {
            name: sample_success(read_tree(path), state.reference_keys)
            for name, (state, path) in paths.items()
            if path.exists()
        },
    )


def read_gate(label: str, runs: list[str]) -> Arm | None:
    if not runs:
        return None
    directories = [located(run, RUNS_DIRECTORY / "gate_evaluations", "probe_") for run in runs]
    probe_set = json.loads((directories[0] / "checkpoint.json").read_text(encoding="utf-8"))["probe_set"]
    strata = {statement.name: statement.stratum for statement in read_fixed_set(DATA_DIRECTORY / probe_set)}
    return Arm(label, tuple(read_arm_run(directory, strata) for directory in directories))


def interval(found: DifferenceInterval | Difference) -> str:
    return f"{100 * found.difference:+.1f} [{100 * found.lower:+.1f}, {100 * found.upper:+.1f}]"


def main() -> None:
    arguments = parse_arguments()
    if any(len(variant) < 3 for variant in arguments.variant):
        raise SystemExit("--variant needs a label, a learning rate and a held-out run.")
    states = held_out_states()
    variants = [
        Variant(label, float(rate), read_held_out(label, held_out, states), read_gate(label, gate))
        for label, rate, held_out, *gate in arguments.variant
    ]
    if len({variant.gate is None for variant in variants}) > 1 or (variants[0].gate is not None) != bool(
        arguments.v0_gate
    ):
        raise SystemExit("Give gate runs for v0 and every variant, or for none.")
    reports = against_v0(
        variants, read_held_out("v0", arguments.v0, states), read_gate("v0", arguments.v0_gate), arguments.seed
    )
    rows = [
        [
            report.label,
            f"{report.learning_rate:g}",
            interval(report.valid),
            interval(report.success),
            "not run" if report.gate is None else interval(report.gate),
        ]
        for report in reports
    ]
    headers = ["variant", "rate", "held-out valid Lean", "held-out success", "gate set solved"]
    print("Against v0, points [95%]: per held-out state, per gate statement")
    print(markdown_table(headers, rows))
    choice = choose_rate(variants, arguments.seed)
    print(f"\nChosen: {choice.chosen} ({choice.reason}; tied on the held-out states: {', '.join(choice.tied)})")
    for chosen, other in choice.probe_runs:
        print(f"The gate set contradicts the held-out states for {chosen} against {other}: run both on the probe.")


if __name__ == "__main__":
    main()
