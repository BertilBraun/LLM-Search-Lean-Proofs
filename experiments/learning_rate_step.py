"""The follow-up study's step 2, the learning rates, as deployment/study_chain.sh runs it (src/lean_search/rl/
learning_rate_step.py; DESIGN.md, "Follow-up study: controlled arms", "Step 2"; the owner's decisions of 2026-11-16).

    python experiments/learning_rate_step.py check-mode --mode /workspace/runs/study_chain/mode.toml
    python experiments/learning_rate_step.py write-configs --output /workspace/runs/study_chain/configs \
        --shared-run followup_shared_sampling
    python experiments/learning_rate_step.py check-dry-run --log /workspace/runs/study_chain/dry_run_step2_C_w1.log
    python experiments/learning_rate_step.py check-held-out --name step2_A_5e-5
    python experiments/learning_rate_step.py check-round --label C_w4_1e-4
    python experiments/learning_rate_step.py rank-arguments --signal A
    python experiments/learning_rate_step.py report --state /workspace/runs/study_chain --mode .../mode.toml \
        --shared-run followup_shared_sampling --earlier-v0 v0 --output .../learning_rates_report.md

check-mode refuses a sampling mode followup_arm.py would refuse (a search config with a per-search token cap among
them) and prints what it samples with and the search config's sha256. write-configs writes
each round's config (<label>.toml: a GRPO round's phase config or an expert-iteration round's recipe, the arm's at the
variant's rate) and the driver's plan (rounds.tsv, builds.tsv, held_out.tsv), and refuses an output with other contents
(the same contents are written again silently). check-dry-run prints the steps a `grpo_expert_iteration.py train
--dry-run` planned and fails when it would refuse or plans none. check-held-out fails while a held-out run's
summary.json names states it left without a tree (the run is resumed under its name). check-round fails unless a
round's outcome file (phase.json, training_summary.json) reads back whole. rank-arguments prints
rank_learning_rates.py's arguments for one signal, one per line. report ranks every signal as rank_learning_rates.py
does (and fails unless its choice is the one in the state directory's rank_<signal>.txt), reads the rounds' outcomes,
v0's two runs of the step and the driver's timings, and writes the report the step ends with.
"""

import argparse
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from rank_learning_rates import States, held_out_states, read_held_out

from lean_search.rl.expert_iteration_data import TrainingSummary
from lean_search.rl.learning_rate_step import (
    STEP_VARIANTS,
    V0_END_HELD_OUT,
    V0_HELD_OUT,
    ExpertIterationRoundSize,
    GrpoRoundSize,
    PairedRun,
    PlanPaths,
    RoundKind,
    RoundRecord,
    Signal,
    SignalRanking,
    StepReport,
    StepVariant,
    StudyTemplates,
    V0Baseline,
    chosen_label,
    dropped_states,
    dry_run_steps,
    expert_iteration_round_size,
    grpo_round_size,
    mode_description,
    plan_files,
    rank_arguments,
    read_durations,
    report_markdown,
    round_config_text,
    round_outcome_problem,
    run_rates,
    signal_variants,
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
RECIPE = FOLLOWUP / "expert_iteration.toml"
ARM_OVERLAYS = {signal: FOLLOWUP / "arms" / f"{signal}.toml" for signal in Signal}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check_mode = commands.add_parser("check-mode")
    check_mode.add_argument("--mode", type=Path, required=True)
    write_configs = commands.add_parser("write-configs")
    write_configs.add_argument("--output", type=Path, required=True)
    write_configs.add_argument("--shared-run", required=True)
    check_dry_run = commands.add_parser("check-dry-run")
    check_dry_run.add_argument("--log", type=Path, required=True)
    check_held_out = commands.add_parser("check-held-out")
    check_held_out.add_argument("--name", required=True, help="held_out_evaluations/held_out_<name>")
    check_round = commands.add_parser("check-round")
    check_round.add_argument("--label", required=True, choices=[variant.label for variant in STEP_VARIANTS])
    arguments = commands.add_parser("rank-arguments")
    arguments.add_argument("--signal", type=Signal, choices=list(Signal), required=True)
    report = commands.add_parser("report")
    report.add_argument("--state", type=Path, required=True, help="the driver's state directory")
    report.add_argument("--mode", type=Path, required=True)
    report.add_argument("--shared-run", required=True)
    report.add_argument("--earlier-v0", required=True, help="v0's earlier held-out run, compared descriptively")
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
        base,
        read_toml(REPOSITORY_DIRECTORY / base["training"]["phase_config"]),
        read_toml(RECIPE),
        {signal: read_toml(path) for signal, path in ARM_OVERLAYS.items()},
    )
    texts = {f"{variant.label}.toml": round_config_text(variant, templates, shared_run) for variant in STEP_VARIANTS}
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
    texts |= {"rounds.tsv": plan.rounds, "builds.tsv": plan.builds, "held_out.tsv": plan.held_out}
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


def check_dry_run(log: Path) -> None:
    try:
        steps = dry_run_steps(log.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SystemExit(f"{log}: {error}") from error
    print(f"{steps} steps")


def check_round(label: str) -> None:
    variant = next(variant for variant in STEP_VARIANTS if variant.label == label)
    problem = round_outcome_problem(variant, environment_path("LEAN_SEARCH_CHECKPOINTS"))
    if problem is not None:
        raise SystemExit(problem)
    print(f"{label}: its outcome file reads back")


def check_held_out(name: str) -> None:
    summary = environment_path("LEAN_SEARCH_RUNS") / "held_out_evaluations" / f"held_out_{name}" / "summary.json"
    dropped = dropped_states(summary.read_text(encoding="utf-8"))
    if dropped:
        raise SystemExit(f"{summary}: {len(dropped)} states without a tree, e.g. {dropped[0]}; run it again to resume.")
    print(f"{name}: every state sampled")


def round_record(variant: StepVariant, state: Path, checkpoints: Path, durations: dict[str, float]) -> RoundRecord:
    output = checkpoints / variant.run_name
    size: GrpoRoundSize | ExpertIterationRoundSize
    match variant.kind:
        case RoundKind.GRPO:
            size = grpo_round_size(
                from_json_object(PhaseOutcome, json.loads((output / "phase.json").read_text(encoding="utf-8")))
            )
        case RoundKind.EXPERT_ITERATION:
            summary = from_json_object(
                TrainingSummary, json.loads((output / "training_summary.json").read_text(encoding="utf-8"))
            )
            planned = dry_run_steps((state / f"dry_run_{variant.build_name}.log").read_text(encoding="utf-8"))
            size = expert_iteration_round_size(summary, planned)
    return RoundRecord(variant, size, durations[f"round_{variant.label}"])


def signal_ranking(signal: Signal, v0: HeldOutStates, states: States, state: Path) -> SignalRanking:
    variants = [
        Variant(variant.label, variant.learning_rate, read_held_out(variant.label, variant.run_name, states))
        for variant in signal_variants(signal)
    ]
    choice = choose_rate(variants)
    printed = chosen_label((state / f"rank_{signal}.txt").read_text(encoding="utf-8"))
    if printed != choice.chosen:
        raise SystemExit(f"rank_{signal}.txt chose {printed}, this report {choice.chosen}: look before using either.")
    return SignalRanking(signal, against_v0(variants, v0, None), choice)


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
    rankings = tuple(signal_ranking(signal, v0, states, arguments.state) for signal in Signal)
    durations = read_durations((arguments.state / "timings.tsv").read_text(encoding="utf-8"))
    checkpoints = environment_path("LEAN_SEARCH_CHECKPOINTS")
    finished_path = environment_path("LEAN_SEARCH_RUNS") / arguments.shared_run / "finished.json"
    finished = from_json_object(RunFinished, json.loads(finished_path.read_text(encoding="utf-8")))
    step = StepReport(
        git_revision(),
        mode.description,
        finished.generated_tokens,
        finished.lost_tokens,
        rankings,
        tuple(round_record(variant, arguments.state, checkpoints, durations) for variant in STEP_VARIANTS),
        v0_baseline(v0, arguments.earlier_v0, states, mode.visible_reasoning),
        durations,
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
        case "check-dry-run":
            check_dry_run(arguments.log)
        case "check-round":
            check_round(arguments.label)
        case "check-held-out":
            check_held_out(arguments.name)
        case "rank-arguments":
            print("\n".join(rank_arguments(arguments.signal)))
        case "report":
            report(arguments)


if __name__ == "__main__":
    main()
