"""The steps of deployment/arms_chain.sh that hold logic (src/lean_search/rl/arms_chain.py).

    python experiments/arms_chain.py smoke-overlays --output <state>/smoke/overlays
    python experiments/arms_chain.py adapters --run $LEAN_SEARCH_RUNS/followup_A --output <state>/adapters/A
    python experiments/arms_chain.py probe-list --arm A --run <run> --output <state>/probe/runs_A.toml
    python experiments/arms_chain.py compare-plan --arm C --state <state>
    python experiments/arms_chain.py report --arm A --run <run> --state <state> --probe-runs <probe evaluations>
    python experiments/arms_chain.py health-report --arm A --run <run>
    python experiments/arms_chain.py smoke-check --runs $LEAN_SEARCH_RUNS --checkpoints $LEAN_SEARCH_CHECKPOINTS \
        --state <state> --output <state>/smoke_report.md

smoke-overlays writes C.toml and D.toml, the arms' overlays with the smoke's name and budget (`smoke_overlay`).
adapters copies the arm's phase-8 and final policy and value adapters with a sha256 manifest. probe-list writes the
arm's one probe run (exit 1 when a health-stopped arm has no healthy phase to evaluate). compare-plan prints, one per
line and tab-separated, the output file, the x run and label, the y label and the y runs (space-separated): against
the anchors, run 7 and every earlier arm with a probe run done. report and health-report print markdown. smoke-check
writes the smoke report and exits 0 when every gate passed, 3 when one failed.
"""

import argparse
import tomllib
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.arms_chain import (
    ARMS,
    SMOKE_ARMS,
    SMOKE_KILLED_ARM,
    SMOKE_PHASES,
    SmokeRun,
    arm_report,
    comparisons,
    final_checkpoint,
    health_report,
    phase_directory_name,
    probe_list_text,
    pull_adapters,
    smoke_checks,
    smoke_overlay,
    smoke_report,
    smoke_run_name,
)
from lean_search.rl.probe_evaluation import run_directory
from lean_search.rl.probe_run_list import read_run_list

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
ARMS_DIRECTORY = REPOSITORY_DIRECTORY / "experiments/configs/grpo/followup/arms"
FAILED_EXIT_STATUS = 3


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("smoke-overlays").add_argument("--output", type=Path, required=True)
    adapters = commands.add_parser("adapters")
    adapters.add_argument("--run", type=Path, required=True)
    adapters.add_argument("--output", type=Path, required=True)
    probe_list = commands.add_parser("probe-list")
    probe_list.add_argument("--arm", choices=ARMS, required=True)
    probe_list.add_argument("--run", type=Path, required=True)
    probe_list.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser("compare-plan")
    plan.add_argument("--arm", choices=ARMS, required=True)
    plan.add_argument("--state", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("--arm", choices=ARMS, required=True)
    report.add_argument("--run", type=Path, required=True)
    report.add_argument("--state", type=Path, required=True)
    report.add_argument("--probe-runs", type=Path, required=True, help="the probe evaluations' directory")
    health = commands.add_parser("health-report")
    health.add_argument("--arm", choices=ARMS, required=True)
    health.add_argument("--run", type=Path, required=True)
    smoke = commands.add_parser("smoke-check")
    smoke.add_argument("--runs", type=Path, required=True)
    smoke.add_argument("--checkpoints", type=Path, required=True)
    smoke.add_argument("--state", type=Path, required=True)
    smoke.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def probe_list_path(state: Path, arm: str) -> Path:
    return state / "probe" / f"runs_{arm}.toml"


def probe_name(state: Path, arm: str) -> str:
    """The arm's probe run as its list names it."""
    (run,) = read_run_list(probe_list_path(state, arm)).runs
    return run.name


def write_smoke_overlays(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for arm in SMOKE_ARMS:
        overlay = tomllib.loads((ARMS_DIRECTORY / f"{arm}.toml").read_text(encoding="utf-8"))
        text = f"# arms/{arm}.toml as a smoke run (experiments/arms_chain.py smoke-overlays).\n"
        (output / f"{arm}.toml").write_text(text + toml_text(smoke_overlay(overlay, arm)), encoding="utf-8")
        print(output / f"{arm}.toml")


def write_probe_list(arm: str, run: Path, output: Path) -> None:
    checkpoint = final_checkpoint(run)
    if checkpoint is None:
        raise SystemExit(f"{run}: the health stop's last good version is version 0; no phase to evaluate")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(probe_list_text(arm, checkpoint), encoding="utf-8")
    print(f"{output}: phase {checkpoint.phase}, version {checkpoint.version.version}")


def print_compare_plan(arm: str, state: Path) -> None:
    earlier = [
        (other, probe_name(state, other))
        for other in ARMS[: ARMS.index(arm)]
        if (state / f"done_probe_{other}").exists()
    ]
    for comparison in comparisons(arm, probe_name(state, arm), earlier):
        fields = [comparison.file_name, comparison.x_run, comparison.x_label, comparison.y_label]
        print("\t".join([*fields, " ".join(comparison.y_runs)]))


def print_report(arm: str, run: Path, state: Path, probe_runs: Path) -> None:
    probed = (state / f"done_probe_{arm}").exists()
    probe_directory = run_directory(probe_runs, probe_name(state, arm)) if probed else None
    files = sorted(path.name for path in (state / "compare").glob(f"{arm}_against_*.txt"))
    print(arm_report(arm, run, probe_directory, files, state / "adapters" / arm))


def check_smoke(runs: Path, checkpoints: Path, state: Path, output: Path) -> None:
    results = []
    for arm in SMOKE_ARMS:
        name = smoke_run_name(arm)
        smoke = SmokeRun(
            arm,
            runs / name,
            checkpoints / phase_directory_name(name, SMOKE_PHASES),
            state / "smoke" / f"readings_{arm}.tsv",
            state / "smoke" / f"kill_{arm}.json" if arm == SMOKE_KILLED_ARM else None,
        )
        results.append((smoke, smoke_checks(smoke)))
    passed, report = smoke_report(results)
    output.write_text(report, encoding="utf-8")
    failed = [
        f"{run.arm} {check.name}" for run, checks in results for check in checks if check.gate and not check.passed
    ]
    print("passed" if passed else f"failed: {', '.join(failed)}")
    if not passed:
        raise SystemExit(FAILED_EXIT_STATUS)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "smoke-overlays":
            write_smoke_overlays(arguments.output)
        case "adapters":
            pulled = pull_adapters(arguments.run, arguments.output)
            print(f"{arguments.output}: " + ", ".join(f"phase {adapter.phase} {adapter.model}" for adapter in pulled))
        case "probe-list":
            write_probe_list(arguments.arm, arguments.run, arguments.output)
        case "compare-plan":
            print_compare_plan(arguments.arm, arguments.state)
        case "report":
            print_report(arguments.arm, arguments.run, arguments.state, arguments.probe_runs)
        case "health-report":
            print(health_report(arguments.arm, arguments.run))
        case "smoke-check":
            check_smoke(arguments.runs, arguments.checkpoints, arguments.state, arguments.output)


if __name__ == "__main__":
    main()
