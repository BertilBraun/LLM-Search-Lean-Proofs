"""Set up, inspect and operate the continuous expert-iteration loop.

    python experiments/phase6_loop.py --config experiments/configs/expert_iteration/loop.toml init
    python experiments/phase6_loop.py --config ... status | metrics | serve-commands | commands

init writes version 0 (the configured initial adapters) and refuses an existing loop. status prints the current
version, the time since the last phase, statements processed, proofs found, the search service's heartbeat and the
training phase in progress. metrics computes per-version solve rates, proofs per hour and value calibration on fresh
trees, each budget stage's proofs per GPU-hour (to tune the stage gates), and the phases' buffer statistics, into
$LEAN_SEARCH_RUNS/<loop>/summary/{metrics.json,README.md}.
serve-commands prints how to start each vLLM server with the current version (also after a reboot); commands prints
how to start every process.
"""

import argparse
import dataclasses
import datetime
import json
import os
import shutil
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.digests import all_values
from lean_search.expert_iteration.loop_config import LoopConfig, load_loop_config
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
    read_current,
    record_published,
)
from lean_search.expert_iteration.shards import all_attempts, now
from lean_search.expert_iteration.trainer import PhaseRecord, PhaseStage, read_phase_state
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


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
    return parser.parse_args()


def read_phases(paths: LoopPaths) -> list[PhaseRecord]:
    if not paths.phases.exists():
        return []
    with paths.phases.open(encoding="utf-8") as lines:
        return [from_json_object(PhaseRecord, json.loads(line)) for line in lines if line.strip()]


def initialize(config: LoopConfig, config_path: Path, paths: LoopPaths) -> None:
    if paths.current.exists():
        raise ValueError(f"{paths.directory} already holds a loop; status shows where it stands.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, paths.config)
    version = ModelVersion(0, config.initial.policy_adapter, config.initial.value_adapter, now(), "initial")
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


def print_status(paths: LoopPaths) -> None:
    current = read_current(paths)
    totals = run_totals(list(all_attempts(paths.shards)), datetime.datetime.now(datetime.UTC))
    lines = [
        f"Loop {paths.directory}",
        f"Version {current.version} (published {current.published_at}, {age_minutes(current.published_at):.0f} min "
        f"ago, trigger {current.trigger}); policy {current.policy_adapter}, value {current.value_adapter}",
        f"Statements processed {totals.statements:,}, solved {totals.solved_statements:,}, {totals.proofs:,} proofs "
        f"(with harvested ones); {totals.attempts:,} stage records; last hour: {totals.attempts_last_hour:,} stages, "
        f"{totals.proofs_last_hour:,} proofs",
    ]
    if paths.heartbeat.exists():
        heartbeat = from_json_object(ServiceHeartbeat, json.loads(paths.heartbeat.read_text(encoding="utf-8")))
        counts = heartbeat.scheduler
        activity = "paused" if heartbeat.paused else "running"
        lines.append(
            f"Search service ({age_minutes(heartbeat.written_at):.1f} min ago, {activity}"
            f", version {heartbeat.version}): {heartbeat.live_searches} searches in flight (by stage "
            f"{'/'.join(str(count) for count in heartbeat.live_by_stage)}), {counts.fresh:,} fresh, {counts.queued:,} "
            f"queued to restart, {counts.solved:,} solved, {counts.retired:,} retired; this session "
            f"{heartbeat.session_attempts:,} stages, {heartbeat.session_proofs:,} proofs (+"
            f"{heartbeat.session_harvested_proofs:,} harvested), {heartbeat.session_failures} server errors"
        )
        curriculum = heartbeat.curriculum
        if curriculum is not None:
            rate = "–" if curriculum.solve_rate is None else f"{curriculum.solve_rate:.0%}"
            lines.append(
                f"Curriculum: {curriculum.statements:,} verified statements, {curriculum.available:,} not started; "
                f"band {curriculum.band_low} – {curriculum.band_high} ({curriculum.band_available:,} statements, "
                f"move {curriculum.generation}), solve rate {rate} over {curriculum.outcomes} outcomes; "
                f"{curriculum.roots_scored_by_current_model:,} roots scored by the current value model"
            )
    else:
        lines.append("Search service: no heartbeat yet")
    state = read_phase_state(paths)
    if state is not None and state.stage != PhaseStage.DONE:
        lines.append(f"Training phase {state.phase} at {state.stage} (started {state.started_at}, {state.trigger})")
    phases = read_phases(paths)
    if phases and phases[-1].data is not None:
        data = phases[-1].data
        lines.append(
            f"Last phase {phases[-1].phase}: policy buffer {data.policy.size:,}/{data.policy.capacity:,} "
            f"({data.policy.dataset_share:.0%} dataset), {data.policy.added:,} added, {data.policy.trained:,} trained; "
            f"value buffer {data.value.size:,}/{data.value.capacity:,} ({data.value.dataset_share:.0%} dataset), "
            f"{data.value.added:,} added; value gate {'open' if data.gate.open else 'closed'} "
            f"(Spearman {data.gate.spearman}, dead AUC {data.gate.dead_auc})"
        )
    evaluations = read_evaluations(paths.evaluations)
    if evaluations:
        last = evaluations[-1]
        lines.append(f"Last evaluation: version {last.version}, {last.solved}/{last.problems} on miniF2F-valid")
    print("\n".join(lines))


def optional(value: float | None, specification: str) -> str:
    return "–" if value is None else format(value, specification)


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
        stages=tuple(stage_metrics(attempts, len(config.serving.servers), searched)),
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
            f"next stage, expansions, GPU-hours (the {len(config.serving.servers)} servers' search time "
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


def print_commands(config_path: Path, paths: LoopPaths) -> None:
    config = f"--config {config_path.as_posix()}"
    log = f"$LEAN_SEARCH_RUNS/{paths.name}"
    print(
        "\n".join(
            [
                f"python experiments/phase6_loop.py {config} init",
                "# start the servers with the commands init (or serve-commands) prints, then:",
                "# the searches' Lean REPLs are the CPU load: 40 pinned CPUs (deployment/README.md, CPU budget)",
                "BACKGROUND_CPUS=40 setsid nohup deployment/background.sh python experiments/phase6_service.py "
                f"{config} >> {log}/service.log 2>&1 < /dev/null &",
                f"BACKGROUND_CPUS=40 setsid nohup deployment/background.sh python experiments/phase6_evaluator.py "
                f"{config} >> {log}/evaluator.log 2>&1 < /dev/null &",
                "# pool v3 verification ahead of the curriculum (shares the 40 background CPUs)",
                "BACKGROUND_CPUS=40 setsid nohup deployment/background.sh python experiments/phase6_pool_v3.py "
                "--config experiments/configs/expert_iteration/pool_v3.toml --step verify "
                f"--loop-config {config_path.as_posix()} >> {log}/verify.log 2>&1 < /dev/null &",
                f"python experiments/phase6_loop.py {config} status",
                "# stop a process with kill (SIGTERM) on its python PID; each resumes from disk",
            ]
        )
    )


def main() -> None:
    arguments = parse_arguments()
    config = load_loop_config(arguments.config)
    paths = LoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, config.name)
    match arguments.command:
        case Command.INIT:
            initialize(config, arguments.config, paths)
        case Command.STATUS:
            print_status(paths)
        case Command.METRICS:
            write_metrics(config, paths)
        case Command.SERVE_COMMANDS:
            print_serve_commands(config, paths)
        case Command.COMMANDS:
            print_commands(arguments.config, paths)


if __name__ == "__main__":
    main()
