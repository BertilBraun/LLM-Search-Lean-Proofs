"""Set up, inspect and operate the continuous expert-iteration loop.

    python experiments/phase6_loop.py --config experiments/configs/expert_iteration/loop.toml init
    python experiments/phase6_loop.py --config ... status | metrics | serve-commands | commands

init writes version 0 (the [initial] adapters, or --policy-adapter / --value-adapter, merged into full weights)
and refuses an existing loop.
status prints one block for the watchdog: service alive, version, statements processed, proofs, the last phase, the
curriculum band, GPU utilization and the verifier's lead. metrics computes per-version solve rates, proofs per hour
and value calibration on fresh trees, each budget stage's proofs per GPU-hour (to tune the stage gates), and the
phases' buffer statistics, into $LEAN_SEARCH_RUNS/<loop>/summary/{metrics.json,README.md}.
serve-commands prints how to start each vLLM server with the current version (also after a reboot); commands prints
the launch sequence: init, servers, verifier, service, evaluator, status.
"""

import argparse
import dataclasses
import datetime
import json
import os
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.curriculum import KindOutcomes
from lean_search.expert_iteration.digests import all_values
from lean_search.expert_iteration.known_proofs import read_verified
from lean_search.expert_iteration.loop_config import InitialModels, LoopConfig, load_loop_config
from lean_search.expert_iteration.loop_evaluation import read_evaluations
from lean_search.expert_iteration.loop_metrics import (
    Interval,
    RunTotals,
    StageMetrics,
    VersionMetrics,
    run_totals,
    search_seconds,
    stage_metrics,
    version_metrics,
)
from lean_search.expert_iteration.merging import merged_publisher
from lean_search.expert_iteration.search_service import ServiceHeartbeat
from lean_search.expert_iteration.serving import (
    LoopPaths,
    ModelVersion,
    merged_directory,
    read_current,
    record_published,
    server_port,
)
from lean_search.expert_iteration.shards import all_attempts, now
from lean_search.expert_iteration.trainer import PhaseRecord, PhaseStage, read_phase_state
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
# A heartbeat older than this many heartbeat intervals means the service is gone or hung.
HEARTBEAT_TOLERANCE = 4
VERIFIER_PATTERN = "^python experiments/phase6_pool_v3.py .*--step verify"


class Command(StrEnum):
    INIT = "init"
    STATUS = "status"
    METRICS = "metrics"
    SERVE_COMMANDS = "serve-commands"
    COMMANDS = "commands"


@dataclasses.dataclass(frozen=True)
class LoopMetrics:
    computed_at: str
    current_version: int
    totals: RunTotals
    search_seconds: float
    versions: tuple[VersionMetrics, ...]
    stages: tuple[StageMetrics, ...]
    phases: tuple[PhaseRecord, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", type=Command, choices=list(Command))
    parser.add_argument("--policy-adapter", help="init: version 0's policy adapter instead of [initial] policy_adapter")
    parser.add_argument("--value-adapter", help="init: version 0's value adapter instead of [initial] value_adapter")
    return parser.parse_args()


def read_phases(paths: LoopPaths) -> list[PhaseRecord]:
    if not paths.phases.exists():
        return []
    with paths.phases.open(encoding="utf-8") as lines:
        return [from_json_object(PhaseRecord, json.loads(line)) for line in lines if line.strip()]


def initialize(config: LoopConfig, config_path: Path, paths: LoopPaths, initial: InitialModels) -> None:
    if paths.current.exists():
        raise ValueError(f"{paths.directory} already holds a loop; status shows where it stands.")
    for adapter in (initial.policy_adapter, initial.value_adapter):
        if not (Path(adapter) / "adapter_config.json").exists():
            raise ValueError(f"No adapter at {adapter}.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, paths.config)
    version = ModelVersion(0, initial.policy_adapter, initial.value_adapter, now(), "initial")
    print("Merging the initial adapters into full weights (CPU, about a minute)")
    record_published(paths, merged_publisher(config, CHECKPOINTS_DIRECTORY).prepare(version))
    print(f"Version 0 published in {paths.directory}; start the servers with:")
    print_serve_commands(config, paths)


def print_serve_commands(config: LoopConfig, paths: LoopPaths) -> None:
    publisher = merged_publisher(config, CHECKPOINTS_DIRECTORY)
    current = read_current(paths)
    for server in config.serving.servers:
        print(publisher.serve_command(current, server))


def age_minutes(timestamp: str) -> float:
    return (datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(timestamp)).total_seconds() / 60


def gpu_lines() -> list[str]:
    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return [f"gpus: unavailable ({type(error).__name__})"]
    lines = []
    for row in output.strip().splitlines():
        index, utilization, used, total = (field.strip() for field in row.split(","))
        lines.append(f"gpu {index}: {utilization}% util, {int(used) / 1024:.1f}/{int(total) / 1024:.1f} GiB")
    return lines


def verifier_running() -> bool:
    found = subprocess.run(["pgrep", "-f", VERIFIER_PATTERN], capture_output=True, text=True, check=False)
    return bool(found.stdout.strip())


def verifier_line(config: LoopConfig, started: set[str]) -> str:
    records, _ = read_verified(DATA_DIRECTORY / config.search.curriculum.verified)
    usable = [record for record in records if record.verified and not record.automation_solved]
    lead = sum(record.name not in started for record in usable)
    state = "running" if verifier_running() else "not running"
    return (
        f"verifier: {state}; {len(records):,} checked, {len(usable):,} usable, lead {lead:,} not started "
        f"(launch needs {config.search.curriculum.minimum_statements:,} usable)"
    )


def kind_summary(outcomes: KindOutcomes) -> str:
    rate = "–" if outcomes.solve_rate is None else f"{outcomes.solve_rate:.0%}"
    return f"{outcomes.fed:,} fed, {outcomes.solved:,}/{outcomes.finished:,} solved ({rate})"


def print_status(config: LoopConfig, paths: LoopPaths) -> None:
    """One block for the watchdog: each line `key: value`, alive/stale states spelled out."""
    current_time = datetime.datetime.now(datetime.UTC)
    attempts = list(all_attempts(paths.shards))
    started = {attempt.problem_name for attempt in attempts}
    lines = [f"loop: {paths.directory} at {current_time.isoformat(timespec='seconds')}"]
    if not paths.current.exists():
        lines += ["service: not initialized (phase6_loop.py init)", *gpu_lines(), verifier_line(config, started)]
        print("\n".join(lines))
        return
    current = read_current(paths)
    totals = run_totals(attempts, current_time)
    if paths.heartbeat.exists():
        heartbeat = from_json_object(ServiceHeartbeat, json.loads(paths.heartbeat.read_text(encoding="utf-8")))
        age = age_minutes(heartbeat.written_at)
        alive = age * 60 <= HEARTBEAT_TOLERANCE * config.search.heartbeat_seconds
        activity = "paused for training" if heartbeat.paused else "searching"
        stages = "/".join(str(count) for count in heartbeat.live_by_stage)
        lines.append(
            f"service: {'alive' if alive else 'STALE'} (heartbeat {age:.1f} min ago), {activity}, "
            f"{heartbeat.live_searches} searches in flight (by stage {stages}), {heartbeat.session_failures} server "
            f"errors and {heartbeat.session_rescored_states:,} lazily re-scored states this session"
        )
    else:
        heartbeat = None
        lines.append("service: no heartbeat (not started)")
    lines += [
        f"version: {current.version} (published {age_minutes(current.published_at):.0f} min ago, {current.trigger})",
        f"statements: {totals.statements:,} processed, {totals.solved_statements:,} solved",
        f"proofs: {totals.proofs:,} in all, {totals.proofs_last_hour:,} in the last hour",
    ]
    state = read_phase_state(paths)
    phases = read_phases(paths)
    if state is not None and state.stage != PhaseStage.DONE:
        lines.append(
            f"phase: {state.phase} in progress at {state.stage} (started {age_minutes(state.started_at):.0f} min ago)"
        )
    elif phases:
        last = phases[-1]
        took = age_minutes(last.started_at) - age_minutes(last.finished_at)
        lines.append(
            f"phase: last {last.phase} finished {age_minutes(last.finished_at):.0f} min ago, took {took:.0f} min"
        )
    else:
        lines.append("phase: none yet")
    curriculum = None if heartbeat is None else heartbeat.curriculum
    if curriculum is not None and curriculum.band_low is not None:
        rate = "–" if curriculum.solve_rate is None else f"{curriculum.solve_rate:.0%}"
        lines.append(
            f"curriculum: band {curriculum.band_low:.2f}–{curriculum.band_high:.2f} ({curriculum.band_available:,} "
            f"statements, move {curriculum.generation}), solve rate {rate} over {curriculum.outcomes} outcomes, "
            f"{curriculum.available:,} of {curriculum.statements:,} not started"
        )
        lines.append(
            f"fed this session: verified {kind_summary(curriculum.verified_outcomes)}, unverified "
            f"{kind_summary(curriculum.unverified_outcomes)}"
        )
    else:
        lines.append("curriculum: no band yet")
    lines += gpu_lines()
    lines.append(verifier_line(config, started))
    evaluations = read_evaluations(paths.evaluations)
    if evaluations:
        last_evaluation = evaluations[-1]
        lines.append(
            f"evaluation: version {last_evaluation.version} {last_evaluation.solved}/{last_evaluation.problems} "
            "on miniF2F-valid"
        )
    print("\n".join(lines))


def optional(value: float | None, specification: str) -> str:
    return "–" if value is None else format(value, specification)


def gpu_count(config: LoopConfig) -> int:
    return len({server.gpu for server in config.serving.servers})


def write_metrics(config: LoopConfig, paths: LoopPaths) -> None:
    attempts = list(all_attempts(paths.shards))
    phases = read_phases(paths)
    searched = search_seconds(attempts, [Interval(phase.started_at, phase.finished_at) for phase in phases])
    metrics = LoopMetrics(
        computed_at=now(),
        current_version=read_current(paths).version,
        totals=run_totals(attempts, datetime.datetime.now(datetime.UTC)),
        search_seconds=searched,
        versions=tuple(version_metrics(attempts, all_values(paths.digests))),
        stages=tuple(stage_metrics(attempts, gpu_count(config), searched)),
        phases=tuple(phases),
    )
    version_rows = [
        [
            entry.version,
            f"{entry.attempts:,}",
            f"{entry.first_stage_solved:,}/{entry.first_stage_attempts:,}",
            f"{entry.later_stage_solved:,}/{entry.later_stage_attempts:,}",
            f"{entry.proofs_per_hour:.0f}",
            f"{entry.attempts_per_hour:.0f}",
            optional(entry.spearman, ".3f"),
            optional(entry.dead_auc, ".3f"),
        ]
        for entry in metrics.versions
    ]
    stage_rows = [
        [
            entry.stage,
            f"{entry.attempts:,}",
            f"{entry.solved:,}",
            f"{entry.proofs:,}",
            f"{entry.escalated:,}",
            f"{entry.expansions:,}",
            f"{entry.gpu_seconds / 3600:.1f}",
            f"{entry.proofs_per_gpu_hour:.1f}",
            f"{entry.mean_wall_seconds:.0f}",
        ]
        for entry in metrics.stages
    ]
    phase_rows = [
        [
            record.phase,
            record.trigger,
            f"{record.data.policy.added:,} / {record.data.policy.trained:,}",
            f"{record.data.policy.capacity:,} ({record.data.policy.dataset_share:.0%})",
            f"{record.data.value.added:,} / {record.data.value.trained:,}",
            f"{record.data.value.capacity:,} ({record.data.value.dataset_share:.0%})",
            "open" if record.data.gate.open else "closed",
            f"{record.data.jump_pairs_used:,}",
        ]
        for record in metrics.phases
        if record.data is not None
    ]
    evaluations = [
        [record.version, record.run_name, f"{record.solved}/{record.problems}", record.finished_at]
        for record in read_evaluations(paths.evaluations)
    ]
    totals = metrics.totals
    markdown = "\n\n".join(
        [
            f"# Expert-iteration loop `{paths.name}`",
            f"Computed {metrics.computed_at}; version {metrics.current_version}. {totals.statements:,} statements "
            f"processed, {totals.solved_statements:,} solved, {totals.attempts:,} attempts.",
            "## Per model version",
            "Solve rates on the pool by pass; proofs and attempts per hour over the version's active time; Spearman "
            "of the search's h with the exact remaining steps and dead AUC (h separating dead from exact states), "
            "both on the version's digested trees.",
            markdown_table(
                [
                    "Version",
                    "Attempts",
                    "First stage solved",
                    "Later stages solved",
                    "Proofs/h",
                    "Attempts/h",
                    "Spearman",
                    "Dead AUC",
                ],
                version_rows,
            ),
            "## Per budget stage",
            "Stage records, statements solved in the stage, proofs with harvested ones, statements escalated to the "
            f"next stage, expansions, GPU-hours (the {gpu_count(config)} GPUs' search time "
            f"{metrics.search_seconds / 3600:.1f} h attributed by generated tokens), proofs per GPU-hour and the mean "
            "stage wall time (s).",
            markdown_table(
                [
                    "Stage",
                    "Records",
                    "Solved",
                    "Proofs",
                    "Escalated",
                    "Expansions",
                    "GPU-hours",
                    "Proofs/GPU-hour",
                    "Wall (s)",
                ],
                stage_rows,
            ),
            "## Training phases",
            "Added / trained samples per buffer (reuse = trained / added), capacity and dataset share after the "
            "phase, the value gate and the value-jump pairs it let in.",
            markdown_table(
                [
                    "Phase",
                    "Trigger",
                    "Policy added / trained",
                    "Policy capacity",
                    "Value added / trained",
                    "Value capacity",
                    "Gate",
                    "Jump pairs",
                ],
                phase_rows,
            ),
            "## miniF2F-valid evaluations (reduced budget)",
            markdown_table(["Version", "Run", "Solved", "Finished"], evaluations),
        ]
    )
    paths.summary.mkdir(parents=True, exist_ok=True)
    (paths.summary / "metrics.json").write_text(
        json.dumps(dataclasses.asdict(metrics), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (paths.summary / "README.md").write_text(markdown + "\n", encoding="utf-8")
    print(markdown)


def print_commands(config: LoopConfig, config_path: Path, paths: LoopPaths) -> None:
    """The launch sequence, in order (run from the repository on the node)."""
    option = f"--config {config_path.as_posix()}"
    log = f"$LEAN_SEARCH_RUNS/{paths.name}"
    publisher = merged_publisher(config, CHECKPOINTS_DIRECTORY)
    initial = ModelVersion(
        0,
        config.initial.policy_adapter,
        config.initial.value_adapter,
        "",
        "initial",
        str(merged_directory(publisher.weights_root, 0, "policy")),
        str(merged_directory(publisher.weights_root, 0, "value")),
    )
    ports = " ".join(str(server_port(server)) for server in config.serving.servers)
    background = "BACKGROUND_CPUS=40 setsid nohup deployment/background.sh python"
    print(
        "\n".join(
            [
                "# 1. Version 0: merge the initial policy and value adapters into full weights (CPU, about a minute)",
                f"python experiments/phase6_loop.py {option} init --policy-adapter "
                f"{config.initial.policy_adapter} --value-adapter {config.initial.value_adapter}",
                "# 2. Servers: per GPU the merged policy and the merged value, in sleep mode for the phases",
                *(publisher.serve_command(initial, server) for server in config.serving.servers),
                f"for port in {ports}; do until curl -sf http://127.0.0.1:$port/v1/models > /dev/null; do sleep 10; "
                "done; done",
                "# 3. The verifier at its loop setting (6 Lean processes): stop the faster pre-launch one by its PID",
                f'kill $(pgrep -f "{VERIFIER_PATTERN}")',
                f"{background} experiments/phase6_pool_v3.py --config experiments/configs/expert_iteration/pool_v3.toml"
                f" --step verify --loop-config {config_path.as_posix()} >> {log}/verify.log 2>&1 < /dev/null &",
                "# 4. The search service with its training phases (searches start at "
                f"{config.search.curriculum.minimum_statements:,} usable statements), then the evaluator",
                f"{background} experiments/phase6_service.py {option} >> {log}/service.log 2>&1 < /dev/null &",
                f"{background} experiments/phase6_evaluator.py {option} >> {log}/evaluator.log 2>&1 < /dev/null &",
                "# 5. Watch: one status block (service, version, statements, proofs, phase, band, GPUs, verifier)",
                f"python experiments/phase6_loop.py {option} status",
                "# Stop a process with kill (SIGTERM) on its python PID; each resumes from disk.",
            ]
        )
    )


def main() -> None:
    arguments = parse_arguments()
    config = load_loop_config(arguments.config)
    paths = LoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, config.name)
    match arguments.command:
        case Command.INIT:
            initial = InitialModels(
                arguments.policy_adapter or config.initial.policy_adapter,
                arguments.value_adapter or config.initial.value_adapter,
            )
            initialize(config, arguments.config, paths, initial)
        case Command.STATUS:
            print_status(config, paths)
        case Command.METRICS:
            write_metrics(config, paths)
        case Command.SERVE_COMMANDS:
            print_serve_commands(config, paths)
        case Command.COMMANDS:
            print_commands(config, arguments.config, paths)


if __name__ == "__main__":
    main()
