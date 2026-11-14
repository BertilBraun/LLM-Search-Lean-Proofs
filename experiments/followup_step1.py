"""Step 1's two measured settings (src/lean_search/rl/step1_settings.py; DESIGN.md, "Follow-up study: controlled arms",
"Step 1").

    python experiments/followup_step1.py token-budget \
        $LEAN_SEARCH_RUNS/probe_evaluations/probe_step1_run1_v0_value_v0 [.../probe_step1_run2_v0_value_v0]
    python experiments/followup_step1.py automation-constant \
        $LEAN_SEARCH_RUNS/calibration_evaluations/probe_calibration_{completion,block_sum,block_mean}

token-budget reads accepted anchor runs (probe_evaluate.py --anchor: v0 with value v0 at 16 expansions) and prints v0's
mean generated tokens per expansion (their searches' tokens over their expansions), T = 16 x it for runs 3 and 4 and
T64 = 64 x it for the miniF2F token runs, with the line to set in step1/token_capped_*.toml. automation-constant reads
the calibration runs (step1/runs_calibration.toml: one expansion without a value model per calibration statement) and
prints, per run, the [value_free_priority] table for step1/value_free_<setting>.toml: the setting the run searched with
and the median step log-probability of its root samples that made progress (ran completely, changed the goals).
"""

import argparse
import json
from pathlib import Path

from lean_search.rl.evaluation import EvaluationPaths
from lean_search.rl.step1_settings import (
    MINIF2F_TOKEN_CAP_EXPANSIONS,
    TOKEN_CAP_EXPANSIONS,
    automation_constant,
    progressing_step_values,
    token_budget,
)
from lean_search.search import load_run_config, read_results, read_tree


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("token-budget").add_argument("runs", nargs="+", type=Path)
    commands.add_parser("automation-constant").add_argument("runs", nargs="+", type=Path)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require_accepted(directory: Path) -> None:
    record = directory / "run.json"
    if not record.exists() or not read_json(record)["accepted"]:
        raise SystemExit(f"{directory} is not an accepted probe_evaluate.py run.")


def print_token_budget(runs: list[Path]) -> None:
    for directory in runs:
        require_accepted(directory)
        if not read_json(directory / "checkpoint.json")["anchor"]:
            raise SystemExit(f"{directory} is not an anchor run (probe_evaluate.py --anchor).")
    budget = token_budget(result for directory in runs for result in read_results(EvaluationPaths(directory).results))
    print(
        f"{budget.searches} searches, {budget.expansions:,} expansions, {budget.generated_tokens:,} generated tokens: "
        f"{budget.tokens_per_expansion:,.0f} per expansion"
    )
    print(f"T   = {TOKEN_CAP_EXPANSIONS} x that = {budget.cap(TOKEN_CAP_EXPANSIONS):,}")
    print(f"T64 = {MINIF2F_TOKEN_CAP_EXPANSIONS} x that = {budget.cap(MINIF2F_TOKEN_CAP_EXPANSIONS):,}")
    print("\nIn experiments/configs/grpo/followup/step1/token_capped_{visible,no_reasoning}.toml, [search]:")
    print(f"max_generated_tokens = {budget.cap(TOKEN_CAP_EXPANSIONS)}")


def print_automation_constants(runs: list[Path]) -> None:
    for directory in runs:
        require_accepted(directory)
        paths = EvaluationPaths(directory)
        setting = load_run_config(paths.config).policy.step_log_probability
        values = [
            value
            for path in sorted(paths.trees.glob("*.json.gz"))
            for value in progressing_step_values(read_tree(path))
        ]
        constant = automation_constant(setting, values)
        print(f"# {directory.name}: for experiments/configs/grpo/followup/step1/value_free_{setting}.toml")
        print(constant.table)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "token-budget":
            print_token_budget(arguments.runs)
        case "automation-constant":
            print_automation_constants(arguments.runs)


if __name__ == "__main__":
    main()
