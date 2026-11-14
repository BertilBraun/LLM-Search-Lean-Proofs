"""Step 1's two measured settings (src/lean_search/rl/step1_settings.py; DESIGN.md, "Follow-up study: controlled arms",
"Step 1").

    python experiments/followup_step1.py token-budget \
        $LEAN_SEARCH_RUNS/probe_evaluations/probe_step1_run1_v0_value_v0 [.../probe_step1_run2_v0_value_v0]
    HF_HUB_OFFLINE=1 python experiments/followup_step1.py automation-constant \
        $LEAN_SEARCH_RUNS/calibration_evaluations/probe_calibration_v0_value_v0

token-budget reads accepted anchor runs (probe_evaluate.py --anchor: v0 with value v0 at 16 expansions) and prints v0's
mean generated tokens per expansion (their searches' tokens over their expansions), T = 16 x it for runs 3 and 4 and
T64 = 64 x it for the miniF2F token runs, with the line to set in step1/token_capped_*.toml. automation-constant reads
the accepted calibration run (step1/runs_calibration.toml: v0 with value v0, 16 expansions, the 200 calibration
statements; it searched with the completion setting) and prints, for each step_log_probability setting, the
[[value_free_priority.automation_constants]] entry for step1/value_free_<setting>.toml in place of its calibrated =
false placeholder: the median, over every policy step at any depth that ran completely and changed the goals, of its
value under the setting, per edge as the search scores it (the block settings recomputed from the recorded tokens
with the policy tokenizer).
"""

import argparse
import json
from pathlib import Path

import transformers

from lean_search.policy.config import StepLogProbability
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
    commands.add_parser("automation-constant").add_argument("run", type=Path)
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


def print_automation_constants(directory: Path) -> None:
    require_accepted(directory)
    paths = EvaluationPaths(directory)
    config = load_run_config(paths.config)
    if not config.value.model or config.policy.step_log_probability != StepLogProbability.COMPLETION:
        raise SystemExit(f"{directory} is not the calibration run: v0 with value v0, the completion setting.")
    decoder = transformers.AutoTokenizer.from_pretrained(config.policy.tokenizer)
    records = [read_tree(path) for path in sorted(paths.trees.glob("*.json.gz"))]
    for setting in StepLogProbability:
        values = [
            value
            for record in records
            for value in progressing_step_values(record, setting, decoder, config.policy.visible_reasoning)
        ]
        print(f"# {directory.name}: for experiments/configs/grpo/followup/step1/value_free_{setting}.toml")
        print(automation_constant(setting, values).table)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "token-budget":
            print_token_budget(arguments.runs)
        case "automation-constant":
            print_automation_constants(arguments.run)


if __name__ == "__main__":
    main()
