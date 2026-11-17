"""The follow-up study's step 2, arm A's learning rate, as deployment/study_chain.sh runs it (src/lean_search/rl/
learning_rate_step.py; DESIGN.md, "Follow-up study: controlled arms", "Step 2"; the owner's decisions of 2026-11-17).

    python experiments/learning_rate_step.py check-mode --mode /workspace/runs/study_chain/mode.toml
    python experiments/learning_rate_step.py write-configs --output /workspace/runs/study_chain/configs \
        --shared-run followup_shared_sampling
    python experiments/learning_rate_step.py check-held-out --name step2_A_5e-5
    python experiments/learning_rate_step.py check-round --label A_1e-4
    python experiments/learning_rate_step.py rank-arguments
    python experiments/learning_rate_step.py report --state /workspace/runs/study_chain --mode .../mode.toml \
        --shared-run followup_shared_sampling --earlier-v0 v0 \
        --o2-ranking /workspace/runs/offline_chain/rank_matched.txt --output .../learning_rates_report.md

check-mode refuses a sampling mode followup_arm.py would refuse (a search config with a per-search token cap among
them) and prints what it samples with and the search config's sha256. write-configs writes each round's phase config
(<label>.toml: arm A's at the variant's rate) and the driver's plan (rounds.tsv, held_out.tsv), and refuses an output
with other contents (the same contents are written again silently). check-held-out fails while a held-out run's
summary.json names states it left without a tree (the run is resumed under its name). check-round fails unless a
round's phase.json reads back whole. rank-arguments prints rank_learning_rates.py's arguments for A, one per line.
report ranks A's variants as rank_learning_rates.py does (and fails unless its choice is the one in the state
directory's rank_A.txt), reads the rounds' outcomes, v0's two runs of the step and the driver's timings, and writes the
report the step ends with; arms C and D's rate is O2's (--o2-ranking), named there for the orchestrator to fill.
"""

import argparse
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from rank_learning_rates import States, held_out_states, read_held_out

from lean_search.rl.learning_rate_step import (
    STEP_VARIANTS,
    V0_END_HELD_OUT,
    V0_HELD_OUT,
    PairedRun,
    PlanPaths,
    Ranking,
    RoundRecord,
    StepReport,
    StepVariant,
    StudyTemplates,
    V0Baseline,
    chosen_label,
    dropped_states,
    grpo_round_size,
    mode_description,
    plan_files,
    rank_arguments,
    read_durations,
    report_markdown,
    round_config_text,
    round_outcome_file,
    round_outcome_problem,
    run_rates,
    variant_of,
)
from lean_search.rl.loop import RunFinished
from lean_search.rl.rate_ranking import (
    HeldOutStates,
    Variant,
    against_v0,
    choose_rate,
    paired_states,
    success_rate,
    valid_rate,
)
from lean_search.rl.study_configs import sampling_record, training_search_refusal, with_sampling_mode
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
FOLLOWUP = REPOSITORY_DIRECTORY / "experiments/configs/grpo/followup"
BASE = FOLLOWUP / "base.toml"
ARM_A = FOLLOWUP / "arms" / "A.toml"
RANK_FILE = "rank_A.txt"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check_mode = commands.add_parser("check-mode")
    check_mode.add_argument("--mode", type=Path, required=True)
    write_configs = commands.add_parser("write-configs")
    write_configs.add_argument("--output", type=Path, required=True)
    write_configs.add_argument("--shared-run", required=True)
    check_held_out = commands.add_parser("check-held-out")
    check_held_out.add_argument("--name", required=True, help="held_out_evaluations/held_out_<name>")
    check_round = commands.add_parser("check-round")
    check_round.add_argument("--label", required=True, choices=[variant.label for variant in STEP_VARIANTS])
    commands.add_parser("rank-arguments")
    report = commands.add_parser("report")
    report.add_argument("--state", type=Path, required=True, help="the driver's state directory")
    report.add_argument("--mode", type=Path, required=True)
    report.add_argument("--shared-run", required=True)
    report.add_argument("--earlier-v0", required=True, help="v0's earlier held-out run, compared descriptively")
    report.add_argument("--o2-ranking", required=True, help="the offline run O2's rate choice, which C and D take")
    report.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def environment_path(name: str) -> Path:
    return Path(os.environ[name])


@dataclass(frozen=True)
class SamplingMode:
    description: str
    visible_reasoning: bool
    search_config_sha256: str


def sampling_mode(mode_path: Path) -> SamplingMode:
    """SystemExit for a mode followup_arm.py would refuse."""
    try:
        sampling = with_sampling_mode(read_toml(BASE), read_toml(mode_path))["sampling"]
        run_config = load_run_config(REPOSITORY_DIRECTORY / sampling["search_config"])
    except (ValueError, OSError) as error:
        raise SystemExit(f"{mode_path}: {error}") from error
    refusal = training_search_refusal(run_config)
    if refusal is not None:
        raise SystemExit(f"{mode_path}: {refusal}")
    description = mode_description(sampling["search_config"], run_config, sampling["max_expansions"])
    record = sampling_record(sampling, REPOSITORY_DIRECTORY)
    return SamplingMode(description, run_config.policy.visible_reasoning, record.search_config_sha256)


def write_configs(output: Path, shared_run: str) -> None:
    base = read_toml(BASE)
    templates = StudyTemplates(
        base, read_toml(REPOSITORY_DIRECTORY / base["training"]["phase_config"]), read_toml(ARM_A)
    )
    texts = {f"{variant.label}.toml": round_config_text(variant, templates) for variant in STEP_VARIANTS}
    data = environment_path("LEAN_SEARCH_DATA")
    plan = plan_files(
        PlanPaths(
            output.absolute(),
            environment_path("LEAN_SEARCH_CHECKPOINTS"),
            environment_path("LEAN_SEARCH_RUNS"),
            shared_run,
            base["initial"]["policy_adapter"],
            data / base["training"]["lean_replay"],
            data / base["training"]["math_replay"],
        )
    )
    texts |= {"rounds.tsv": plan.rounds, "held_out.tsv": plan.held_out}
    differing = [
        name
        for name, text in texts.items()
        if (output / name).exists() and (output / name).read_text(encoding="utf-8") != text
    ]
    if differing:
        raise SystemExit(f"{output} holds other {differing}: the step's configs are written once.")
    output.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (output / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {len(texts)} files to {output}")


def check_round(label: str) -> None:
    problem = round_outcome_problem(variant_of(label), environment_path("LEAN_SEARCH_CHECKPOINTS"))
    if problem is not None:
        raise SystemExit(problem)
    print(f"{label}: its phase.json reads back")


def check_held_out(name: str) -> None:
    summary = environment_path("LEAN_SEARCH_RUNS") / "held_out_evaluations" / f"held_out_{name}" / "summary.json"
    dropped = dropped_states(summary.read_text(encoding="utf-8"))
    if dropped:
        raise SystemExit(f"{summary}: {len(dropped)} states without a tree, e.g. {dropped[0]}; run it again to resume.")
    print(f"{name}: every state sampled")


def round_record(variant: StepVariant, checkpoints: Path, durations: dict[str, float]) -> RoundRecord:
    outcome = from_json_object(
        PhaseOutcome, json.loads(round_outcome_file(variant, checkpoints).read_text(encoding="utf-8"))
    )
    return RoundRecord(variant, grpo_round_size(outcome), durations[f"round_{variant.label}"])


def a_ranking(v0: HeldOutStates, states: States, state: Path) -> Ranking:
    variants = [
        Variant(variant.label, variant.learning_rate, read_held_out(variant.label, variant.run_name, states))
        for variant in STEP_VARIANTS
    ]
    choice = choose_rate(variants)
    printed = chosen_label((state / RANK_FILE).read_text(encoding="utf-8"))
    if printed != choice.chosen:
        raise SystemExit(f"{RANK_FILE} chose {printed}, this report {choice.chosen}: look before using either.")
    return Ranking(against_v0(variants, v0, None), choice)


def paired_run(other: HeldOutStates, first: HeldOutStates) -> PairedRun:
    return PairedRun(
        run_rates(other), paired_states(other, first, valid_rate), paired_states(other, first, success_rate)
    )


def earlier_run(v0: HeldOutStates, earlier_name: str, states: States) -> PairedRun | str:
    """Descriptive only: a run that cannot be read against today's states is named, not a failure of the report."""
    try:
        return paired_run(read_held_out(f"{earlier_name} (2026-11-15)", earlier_name, states), v0)
    except (SystemExit, OSError, ValueError) as error:
        return f"{earlier_name}: {error}"


def v0_baseline(v0: HeldOutStates, earlier_name: str, states: States, visible_reasoning: bool) -> V0Baseline:
    end = read_held_out("v0 after the variants", V0_END_HELD_OUT, states)
    return V0Baseline(run_rates(v0), paired_run(end, v0), earlier_run(v0, earlier_name, states), visible_reasoning)


def git_revision() -> str:
    found = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=False
    )
    return found.stdout.strip() if found.returncode == 0 else "of an unknown revision (git rev-parse failed)"


def report(arguments: argparse.Namespace) -> None:
    mode = sampling_mode(arguments.mode)
    states = held_out_states()
    v0 = read_held_out("v0", V0_HELD_OUT, states)
    durations = read_durations((arguments.state / "timings.tsv").read_text(encoding="utf-8"))
    checkpoints = environment_path("LEAN_SEARCH_CHECKPOINTS")
    finished_path = environment_path("LEAN_SEARCH_RUNS") / arguments.shared_run / "finished.json"
    finished = from_json_object(RunFinished, json.loads(finished_path.read_text(encoding="utf-8")))
    step = StepReport(
        git_revision(),
        mode.description,
        finished.generated_tokens,
        finished.lost_tokens,
        a_ranking(v0, states, arguments.state),
        tuple(round_record(variant, checkpoints, durations) for variant in STEP_VARIANTS),
        v0_baseline(v0, arguments.earlier_v0, states, mode.visible_reasoning),
        durations,
        arguments.o2_ranking,
    )
    arguments.output.write_text(report_markdown(step), encoding="utf-8", newline="\n")
    print(f"Wrote {arguments.output}")


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "check-mode":
            mode = sampling_mode(arguments.mode)
            print(f"{mode.description}\nsearch config sha256 {mode.search_config_sha256}")
        case "write-configs":
            write_configs(arguments.output, arguments.shared_run)
        case "check-round":
            check_round(arguments.label)
        case "check-held-out":
            check_held_out(arguments.name)
        case "rank-arguments":
            print("\n".join(rank_arguments()))
        case "report":
            report(arguments)


if __name__ == "__main__":
    main()
