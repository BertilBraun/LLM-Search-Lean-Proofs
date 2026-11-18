"""An arm's loop run directory in the loop's real record formats, phase by phase, for tests/rl/test_arms_chain.py."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.monitoring.families import (
    ExpertIterationPhase,
    GrpoPhase,
    HealthAlert,
    HealthCheck,
    HealthMeasurements,
    HealthSeverity,
    HealthThresholds,
    PhaseHealth,
    RoundSkip,
)
from lean_search.record_fields import record_dict
from lean_search.rl.health_checks import HealthStop
from lean_search.rl.loop import PhaseRecord, RunFinished
from lean_search.rl.training_phase import PhaseOutcome, StageMemory, TrainingStage
from lean_search.search.records import to_json

UPDATES = {"A": "grpo", "C": "expert_iteration", "D": "grpo_and_expert_iteration"}
WAKE_LINE = "GPU memory before the wake: GPU 0 23.1 of 24.0 GiB free, its servers' shares 21.6 GiB"


@dataclass(frozen=True)
class FakeRun:
    runs: Path
    checkpoints: Path
    name: str
    # "grpo", "expert_iteration" or "grpo_and_expert_iteration".
    update: str
    # The loop's value_every_phases (the smoke runs': 1).
    value_every: int = 2

    def trains_value(self, phase: int) -> bool:
        return phase % self.value_every == 0

    @property
    def directory(self) -> Path:
        return self.runs / self.name

    def phase_directory(self, phase: int) -> Path:
        return self.checkpoints / f"{self.name}_phase_{phase:04d}"

    def round_directory(self, phase: int) -> Path:
        return self.directory / "expert_iteration" / f"phase_{phase:04d}"


def adapter(directory: Path, content: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "adapter_config.json").write_text(json.dumps({"r": 64, "of": content}), encoding="utf-8")
    (directory / "adapter_model.safetensors").write_bytes(content.encode() * 64)
    return str(directory)


def append_line(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def log(run: FakeRun, text: str) -> None:
    append_line(run.directory / "loop.log", f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {text}")


def versions(run: FakeRun) -> list[ModelVersion]:
    path = run.directory / "models" / "versions.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ModelVersion(**json.loads(line)) for line in lines if line.strip()]


def initialize(run: FakeRun) -> None:
    """Version 0: v0's policy and value adapters."""
    if versions(run):
        return
    policy = adapter(run.checkpoints / "v0" / "policy", "v0 policy")
    value = adapter(run.checkpoints / "v0" / "value", "v0 value")
    append_line(run.directory / "models" / "versions.jsonl", to_json(ModelVersion(0, policy, value, "now", "initial")))


def metric_line(run: FakeRun, phase: int, record: GrpoPhase | ExpertIterationPhase) -> None:
    line = {"time": time.time(), "phase": phase, "policy_version": phase - 1, "value_version": 0}
    append_line(
        run.directory / "metrics" / f"{record.family}.jsonl", json.dumps(line | {"fields": record_dict(record)})
    )


def grpo_record() -> GrpoPhase:
    return GrpoPhase(
        groups=100,
        group_samples=800,
        mixed_reward_group_share=0.5,
        mean_local_reward=0.1,
        mean_global_reward=0.2,
        kl_to_behaviour_policy=0.01,
        clip_fraction=0.02,
        mean_explanation_tokens=300.0,
        mean_block_tactics=2.0,
        policy_loss=0.0,
        trained_tokens=100_000,
        training_seconds=600.0,
        optimizer_steps=20,
    )


def round_record(skipped: bool = False) -> ExpertIterationPhase:
    return ExpertIterationPhase(
        first_phase=1,
        last_phase=1,
        minimum_version=0,
        solved_trees=40,
        examples=0 if skipped else 300,
        validation_examples=15,
        skipped=skipped,
        skip=RoundSkip.TOO_FEW_EXAMPLES if skipped else None,
        lean_replay_examples=0 if skipped else 90,
        math_replay_examples=0 if skipped else 30,
        optimizer_steps=0 if skipped else 6,
        trained_tokens=0 if skipped else 90_000,
        tokens=0 if skipped else 400_000,
        parameter_change_norm=None if skipped else 0.5,
        phase_parameter_change_norm=None if skipped else 0.8,
        training_seconds=0.0 if skipped else 240.0,
        peak_memory_gib=0.0 if skipped else 18.5,
    )


def train(run: FakeRun, phase: int, skipped_round: bool = False) -> None:
    """What a phase's training leaves: phase.json, the round's build summary and records, the adapters."""
    directory = run.phase_directory(phase)
    adapter(directory / "policy" / "adapter", f"{run.name} policy {phase}")
    if run.update != "grpo":
        adapter(directory / "expert_iteration" / "adapter", f"{run.name} round {phase}")
        summary = run.round_directory(phase) / "summary.json"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text("{}\n", encoding="utf-8")
        log(run, f"Expert-iteration round of phase {phase}, built in 12 s: phases 1-{phase}")
    if run.trains_value(phase):
        adapter(directory / "value" / "adapter", f"{run.name} value {phase}")
    memory = (StageMemory(TrainingStage.EXPERT_ITERATION, 17.0, 19.5),)
    (directory / "phase.json").write_text(to_json(PhaseOutcome(10, 5, None, None, memory=memory)), encoding="utf-8")
    if run.update != "expert_iteration":
        metric_line(run, phase, grpo_record())
    if run.update != "grpo":
        metric_line(run, phase, round_record(skipped_round))


def publish(run: FakeRun, phase: int) -> ModelVersion:
    previous = versions(run)[-1]
    directory = run.phase_directory(phase)
    policy = directory / ("policy" if run.update == "grpo" else "expert_iteration") / "adapter"
    value = str(directory / "value" / "adapter") if run.trains_value(phase) else previous.value_adapter
    version = ModelVersion(previous.version + 1, str(policy), value, "now", f"phase {phase}")
    log(run, WAKE_LINE)
    append_line(run.directory / "models" / "versions.jsonl", to_json(version))
    return version


def close_phase(run: FakeRun, phase: int, version: int, valid: float = 0.6, alert: bool = False) -> None:
    record = PhaseRecord(
        phase, 300, 200, 1800.0, 900.0, 250.0, 400.0, version, phase % 2 == 0, (), "now", generated_tokens=12_000_000
    )
    append_line(run.directory / "phases.jsonl", to_json(record))
    alerts = (
        (HealthAlert(HealthCheck.HELD_OUT_VALID_LEAN, HealthSeverity.STOP, "collapse", "valid Lean below 0.7"),)
        if alert
        else ()
    )
    measured = HealthMeasurements(held_out_valid_rate=valid, held_out_success=0.34)
    health = PhaseHealth(phase, version, measured, HealthThresholds(0.5, 0.1), alerts, hard_stop=alert)
    append_line(run.directory / "health.jsonl", to_json(health))


def finish(run: FakeRun, last_phase: int) -> None:
    (run.directory / "finished.json").write_text(to_json(RunFinished(last_phase, 192_000_000, 0, "now")), "utf-8")


def stop_on_health(run: FakeRun, phase: int, last_good_version: int) -> None:
    stop = HealthStop(phase, phase, last_good_version, "held-out valid Lean below 0.7 of version 0's", "now")
    (run.directory / "health_stop.json").write_text(to_json(stop), encoding="utf-8")


def whole_run(run: FakeRun, phases: int) -> None:
    """An arm that ran all its phases and finished."""
    initialize(run)
    for phase in range(1, phases + 1):
        train(run, phase)
        version = publish(run, phase)
        close_phase(run, phase, version.version)
    finish(run, phases)
