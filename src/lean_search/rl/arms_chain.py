"""The logic of deployment/arms_chain.sh, the node driver that runs the follow-up's closed-loop arms one after another
(DESIGN.md, "Follow-up study: controlled arms", "Step 3"; results/followup_node_operations.md, "The arms driver").

Per arm (A, then C, then D): its loop to `finished.json` (or a health stop, which waits for the owner's word), its
retained policy and value adapters of phase 8 and of its final checkpoint copied to a directory the PC fetches
(`pull_adapters`, with a sha256 manifest), one probe run of the final checkpoint with its own final value model
(`probe_list_text`), the paired comparisons (`comparisons`) and a report (`arm_report`). Before arm C, a smoke test
of expert iteration inside the loop: one phase of arm C and one of arm D at a small budget under their own names
(`smoke_overlay`), judged by explicit criteria (`smoke_checks`).
"""

import dataclasses
import hashlib
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.expert_iteration.toml_text import toml_value
from lean_search.monitoring.families import ExpertIterationPhase, GrpoPhase, RoundSkip
from lean_search.rl.health_checks import HealthStop, read_health_history
from lean_search.rl.loop import PhaseRecord, RunFinished, phase_trigger, read_phase_outcome, value_adapter_version
from lean_search.rl.probe_evaluation import ProbeRunRecord
from lean_search.rl.study_configs import merged
from lean_search.search.records import from_json_object

ARMS = ("A", "C", "D")
SMOKE_ARMS = ("C", "D")
# The one kill during publishing: D's phase publishes GRPO's and the round's update together.
SMOKE_KILLED_ARM = "D"
# Half an arm's phase: its round then trains on a near-real amount of data (at 2M tokens, about 60 examples against the
# loop's floor of 100; reviews BC S3, BD S1).
SMOKE_PHASE_GENERATED_TOKENS = 6_000_000
SMOKE_PHASES = 1
# Retained for the second pass (DESIGN.md, "Evaluation"), beside the final checkpoint.
MIDDLE_PHASE = 8
# The start-order check passed (run 9 against the anchors), so the arms' probe runs start the longest searches first.
PROBE_EVALUATION_CONFIG = "experiments/configs/grpo/followup/step1/probe_evaluation_ordered.toml"
ANCHOR_RUNS = ("step1_run1_v0_value_v0", "step1_run2_v0_value_v0")
V35_FINAL_VALUE_RUN = "step1_run7_v35_value_final"
MANIFEST_FILE = "manifest.sha256"
SOURCES_FILE = "sources.json"
# /dev/shm's use as a gate (the parked models, the policy merge and the value merge); nvidia-smi's used memory while
# training is only a reading: the caching allocator may reserve nearly all of a card without ever failing.
MAX_SHARED_MEMORY_SHARE = 0.9


def run_name(arm: str) -> str:
    return f"followup_{arm}"


def smoke_run_name(arm: str) -> str:
    return f"followup_smoke_{arm}"


def phase_directory_name(run: str, phase: int) -> str:
    """As `GrpoLoopPaths.phase_run_name`: the phase's outputs under the checkpoints."""
    return f"{run}_phase_{phase:04d}"


def smoke_overlay(overlay: Mapping[str, object], arm: str) -> dict[str, object]:
    """The arm's overlay under its smoke name with the smoke's budget, its one phase training the value model too, and a
    round interval longer than the smoke's phases brought within them: D's one phase then trains GRPO, the value model
    and a round in one trainer process, the heaviest pause C and D meet (C at every even phase, D at every fourth)."""
    loop = overlay.get("loop", {})
    assert isinstance(loop, Mapping)
    training = loop.get("training", {})
    assert isinstance(training, Mapping)
    smoke_training: dict[str, object] = {
        "phase_generated_tokens": SMOKE_PHASE_GENERATED_TOKENS,
        "max_phases": SMOKE_PHASES,
        "value_every_phases": SMOKE_PHASES,
    }
    interval = training.get("expert_iteration_every_phases")
    if isinstance(interval, int) and interval > SMOKE_PHASES:
        smoke_training["expert_iteration_every_phases"] = SMOKE_PHASES
    return merged(overlay, {"loop": {"name": smoke_run_name(arm), "training": smoke_training}})


def read_json_lines[T](path: Path, target: type[T]) -> list[T]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [from_json_object(target, json.loads(line)) for line in lines if line.strip()]


def read_versions(run_directory: Path) -> list[ModelVersion]:
    return read_json_lines(run_directory / "models" / "versions.jsonl", ModelVersion)


def phase_of(version: ModelVersion) -> int | None:
    match = re.fullmatch(r"phase (\d+)", version.trigger)
    return int(match.group(1)) if match else None


def published_phases(versions: Sequence[ModelVersion]) -> dict[int, ModelVersion]:
    """Each phase's version (the first published under its trigger)."""
    found: dict[int, ModelVersion] = {}
    for version in versions:
        phase = phase_of(version)
        if phase is not None and phase not in found:
            found[phase] = version
    return found


@dataclass(frozen=True)
class ArmCheckpoint:
    phase: int
    version: ModelVersion
    # The version that first published its value adapter (probe_evaluate.py --value-version).
    value_version: int
    # The phase of the health stop when the arm did not finish.
    stopped_at_phase: int | None = None


def read_health_stop(run_directory: Path) -> HealthStop | None:
    path = run_directory / "health_stop.json"
    return from_json_object(HealthStop, json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def read_finished(run_directory: Path) -> RunFinished | None:
    path = run_directory / "finished.json"
    return from_json_object(RunFinished, json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def final_checkpoint(run_directory: Path) -> ArmCheckpoint | None:
    """A finished arm's last phase, or a health-stopped arm's last good version (DESIGN.md, "Evaluation"); None when
    the stop's last good version is version 0, which no phase trained."""
    versions = read_versions(run_directory)
    phases = published_phases(versions)
    finished = read_finished(run_directory)
    stop = read_health_stop(run_directory)
    if finished is not None:
        phase, stopped_at = finished.last_phase, None
    else:
        assert stop is not None, f"{run_directory} has neither finished.json nor health_stop.json"
        good = next(version for version in versions if version.version == stop.last_good_version)
        found = phase_of(good)
        if found is None:
            return None
        phase, stopped_at = found, stop.phase
    version = phases[phase]
    return ArmCheckpoint(phase, version, value_adapter_version(versions, version.value_adapter), stopped_at)


def adapter_phases(run_directory: Path) -> list[int]:
    """Phase 8 and the final checkpoint's, those that were published."""
    published = published_phases(read_versions(run_directory))
    final = final_checkpoint(run_directory)
    wanted = {MIDDLE_PHASE} | ({final.phase} if final is not None else set())
    return sorted(phase for phase in wanted if phase in published)


@dataclass(frozen=True)
class PulledAdapter:
    phase: int
    version: int
    # "policy" or "value".
    model: str
    source: str
    # Relative to the arm's adapter directory.
    directory: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_text(directory: Path) -> str:
    """sha256sum's format over every file below `directory` but the manifest, so `sha256sum -c` checks a copy."""
    files = sorted(path for path in directory.rglob("*") if path.is_file() and path.name != MANIFEST_FILE)
    return "".join(f"{file_sha256(path)}  {path.relative_to(directory).as_posix()}\n" for path in files)


def manifest_holds(directory: Path) -> bool:
    manifest = directory / MANIFEST_FILE
    return manifest.exists() and manifest.read_text(encoding="utf-8") == manifest_text(directory)


def pull_adapters(run_directory: Path, output: Path) -> list[PulledAdapter]:
    """Copies of the phases' policy and value adapters into `output` (written beside it and renamed into place, the
    manifest last); an output whose manifest holds is kept. ValueError for one whose manifest does not."""
    if output.exists():
        if not manifest_holds(output):
            raise ValueError(f"{output} exists and its {MANIFEST_FILE} does not match its files: move it aside")
        sources = json.loads((output / SOURCES_FILE).read_text(encoding="utf-8"))
        return [from_json_object(PulledAdapter, source) for source in sources]
    phases = published_phases(read_versions(run_directory))
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    pulled = []
    for phase in adapter_phases(run_directory):
        version = phases[phase]
        for model, source in (("policy", version.policy_adapter), ("value", version.value_adapter)):
            directory = f"phase_{phase:04d}/{model}"
            shutil.copytree(source, staging / directory)
            pulled.append(PulledAdapter(phase, version.version, model, source, directory))
    staging.mkdir(parents=True, exist_ok=True)
    sources_text = json.dumps([dataclasses.asdict(adapter) for adapter in pulled], indent=1)
    (staging / SOURCES_FILE).write_text(sources_text + "\n", encoding="utf-8")
    (staging / MANIFEST_FILE).write_text(manifest_text(staging), encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(output)
    return pulled


def probe_run_name(arm: str, phase: int) -> str:
    return f"arm_{arm}_phase{phase}_run1"


def probe_list_text(arm: str, checkpoint: ArmCheckpoint) -> str:
    """The run list (rl/probe_run_list.py) of the arm's one probe run: its final checkpoint with its own value model,
    probe v2 at the anchors' settings, longest expected search first."""
    if checkpoint.stopped_at_phase is None:
        purpose = f"arm {arm}'s final checkpoint (phase {checkpoint.phase}) with its own final value model"
    else:
        purpose = (
            f"arm {arm} stopped at phase {checkpoint.stopped_at_phase}: its last healthy checkpoint (phase "
            f"{checkpoint.phase}) with its own value model"
        )
    settings = {
        "name": probe_run_name(arm, checkpoint.phase),
        "arm": arm,
        "phase": checkpoint.phase,
        "policy_adapter": checkpoint.version.policy_adapter,
        "value": checkpoint.version.value_adapter,
        "value_version": checkpoint.value_version,
        "config": PROBE_EVALUATION_CONFIG,
        "purpose": purpose,
    }
    lines = [f"{key} = {toml_value(value)}" for key, value in settings.items()]
    return (
        "# Written by experiments/arms_chain.py probe-list (deployment/arms_chain.sh).\n[[runs]]\n"
        + "\n".join(lines)
        + "\n"
    )


@dataclass(frozen=True)
class Comparison:
    file_name: str
    x_run: str
    x_label: str
    y_label: str
    y_runs: tuple[str, ...]


def comparisons(arm: str, probe_run: str, earlier: Sequence[tuple[str, str]]) -> list[Comparison]:
    """Against the anchors, against v35 with the final value model (descriptive) and against each other arm's probe
    run done before this one (`earlier`: arm and run name; a health-stopped arm evaluated at the end has them all)."""
    label = f"arm {arm}"
    found = [
        Comparison(f"{arm}_against_anchors.txt", probe_run, label, "v0 anchors", ANCHOR_RUNS),
        Comparison(f"{arm}_against_run7.txt", probe_run, label, "v35 value final", (V35_FINAL_VALUE_RUN,)),
    ]
    found += [
        Comparison(f"{arm}_against_{other}.txt", probe_run, label, f"arm {other}", (other_run,))
        for other, other_run in earlier
    ]
    return found


def metric_lines[T](run_directory: Path, family: str, target: type[T], phase: int) -> list[T]:
    path = run_directory / "metrics" / f"{family}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            parsed = json.loads(line)
            if parsed["phase"] == phase:
                records.append(from_json_object(target, parsed["fields"]))
    return records


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def phases_table(run_directory: Path, phases: Sequence[int]) -> str:
    records = {record.phase: record for record in read_json_lines(run_directory / "phases.jsonl", PhaseRecord)}
    health = {record.phase: record for record in read_health_history(run_directory / "health.jsonl")}
    rows = [
        "| Phase | Version | Trees | Solved | Generated tokens | Sampling h | Training min | Held-out valid | "
        "Held-out success | Alerts |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for phase in phases:
        record = records.get(phase)
        checks = health.get(phase)
        alerts = "-" if checks is None else ", ".join(f"{alert.check} ({alert.severity})" for alert in checks.alerts)
        rows.append(
            f"| {phase} | {'-' if checks is None else checks.policy_version} | "
            f"{'-' if record is None else record.trees} | {'-' if record is None else record.solved_trees} | "
            f"{'-' if record is None else f'{record.generated_tokens:,}'} | "
            f"{'-' if record is None else f'{record.sampling_seconds / 3600:.2f}'} | "
            f"{'-' if record is None else f'{record.training_seconds / 60:.1f}'} | "
            f"{percent(None if checks is None else checks.measured.held_out_valid_rate)} | "
            f"{percent(None if checks is None else checks.measured.held_out_success)} | {alerts or '-'} |"
        )
    return "\n".join(rows)


def loop_hours(run_directory: Path) -> float:
    records = read_json_lines(run_directory / "phases.jsonl", PhaseRecord)
    seconds = sum(
        record.sampling_seconds + record.training_seconds + record.publishing_seconds + record.evaluation_seconds
        for record in records
    )
    return seconds / 3600


def update_lines(run_directory: Path, phases: Sequence[int]) -> list[str]:
    lines = []
    for phase in phases:
        for grpo in metric_lines(run_directory, GrpoPhase.family, GrpoPhase, phase):
            relative = None if grpo.update is None else grpo.update.relative_parameter_change
            change = "-" if relative is None else f"{relative:.4f}"
            lines.append(
                f"- Phase {phase}, GRPO: {grpo.optimizer_steps} steps, {grpo.trained_tokens:,} trained tokens, "
                f"KL to the behaviour policy {grpo.kl_to_behaviour_policy:.4f}, clip {grpo.clip_fraction:.3f}, "
                f"relative LoRA change {change}"
            )
        for round_record in metric_lines(run_directory, ExpertIterationPhase.family, ExpertIterationPhase, phase):
            lines.append(
                f"- Phase {phase}, expert-iteration round: {round_record.examples:,} examples, "
                f"{round_record.optimizer_steps} steps, skipped {round_record.skipped}, replay-loss change "
                f"{percent(round_record.replay_loss_change)}"
            )
    return lines


def health_report(arm: str, run_directory: Path) -> str:
    """What happened when the arm stopped on its health rule, for the owner's decision."""
    stop = read_health_stop(run_directory)
    assert stop is not None, f"{run_directory} has no health_stop.json"
    history = read_health_history(run_directory / "health.jsonl")
    last = [record.phase for record in history][-4:]
    alerts = [
        f"- Phase {record.phase}, {alert.severity} {alert.check}: {alert.detail}"
        for record in history
        if record.phase in last
        for alert in record.alerts
    ]
    return "\n".join(
        [
            f"# Arm {arm} stopped on its health rule",
            "",
            f"- Phase {stop.phase}, version {stop.policy_version} collapsed; last good version "
            f"{stop.last_good_version}; {stop.reason} (at {stop.stopped_at}).",
            "- The owner decides: `skip` (no probe run) or `evaluate` (a probe run of the last good version with its "
            f"value model), written into `word_{arm}` in the chain's state directory. With `on_health_stop` = wait "
            "(the default) the chain is STOPPED until then (move STOPPED aside and start arms_chain); with continue "
            "it goes on with the next arm and asks for the word at the end. A bug found instead: fix it, move the "
            'arm\'s run aside and rerun it (results/followup_node_operations.md, "The arms driver").',
            *(
                ["- **`evaluate` is not possible: no healthy version** (the last good version is 0); write `skip`."]
                if stop.last_good_version == 0
                else []
            ),
            f"- Loop hours so far: {loop_hours(run_directory):.1f}.",
            "",
            "## The last phases",
            "",
            phases_table(run_directory, last),
            "",
            "## Alerts",
            "",
            *(alerts or ["- none"]),
            "",
            "## Policy updates",
            "",
            *(update_lines(run_directory, last) or ["- none recorded"]),
            "",
        ]
    )


def read_probe_record(probe_directory: Path) -> ProbeRunRecord | None:
    path = probe_directory / "run.json"
    return from_json_object(ProbeRunRecord, json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def arm_report(
    arm: str,
    run_directory: Path,
    probe_directory: Path | None,
    comparison_files: Sequence[str],
    adapters: Path,
    revisions: Sequence[str] = (),
) -> str:
    """The arm's loop, the checkouts the driver started it from (`revisions`, "<time> <commit>"), its probe run and
    where the comparisons and adapters are."""
    finished = read_finished(run_directory)
    stop = read_health_stop(run_directory)
    if finished is not None:
        ending = (
            f"finished after phase {finished.last_phase}: {finished.generated_tokens:,} generated tokens counted, "
            f"{finished.lost_tokens:,} lost"
        )
    else:
        assert stop is not None
        ending = f"stopped on its health rule at phase {stop.phase} (last good version {stop.last_good_version})"
    phases = sorted(published_phases(read_versions(run_directory)))
    lines = [
        f"# Arm {arm}",
        "",
        f"- The loop {run_name(arm)} {ending}; {loop_hours(run_directory):.1f} loop hours.",
    ]
    record = None if probe_directory is None else read_probe_record(probe_directory)
    if probe_directory is None:
        lines.append("- No probe run (the owner's word after the health stop).")
    elif record is None:
        lines.append(f"- The probe run {probe_directory.name} has no run.json.")
    else:
        lines.append(
            f"- Probe run {probe_directory.name} (phase {record.start.checkpoint.phase}): **{record.solved:,} of "
            f"{record.problems:,} ({record.solved / record.problems:.2%})**, accepted {record.accepted}, wall-clock "
            f"stops {record.wall_clock_stops} ({record.wall_clock_stop_share:.2%}). Anchors: 713 and 716; v35 with "
            "the final value model (run 7): 1,236."
        )
    started = ", ".join(revisions) if revisions else "none recorded (started by hand, or adopted)"
    lines.append(f"- The driver started its loop from the checkout at: {started}.")
    lines += [f"- Comparison: `{name}`" for name in comparison_files]
    if comparison_files:
        lines.append(
            '- These comparisons use one probe run per arm: provisional (DESIGN.md, "Evaluation": two runs pooled, '
            "at least 3 points with the 95% interval excluding 0, one seed); the second pass adds the second run."
        )
    lines += [
        f"- Adapters (phase 8 and the final checkpoint, policy and value): `{adapters}`, for the PC's "
        "`node_backup/2026-11-15/adapters/` (deployment/pull_arm_adapters.sh).",
        "",
        "## Phases",
        "",
        phases_table(run_directory, phases),
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class SmokeKill:
    """deployment/arms_chain.sh's record of its kill of a smoke loop."""

    killed_at: float
    pid: int
    phase: int
    stage: str
    # How long the stage had been seen before the kill.
    stage_seconds: float


@dataclass(frozen=True)
class ResourceReading:
    """One line of the driver's sampler: one GPU at one moment, with the loop's phase and stage then."""

    time: float
    phase: int
    stage: str
    gpu: int
    used_mib: int
    total_mib: int
    shared_memory_used_kib: int
    shared_memory_size_kib: int


def read_readings(path: Path) -> list[ResourceReading]:
    readings = []
    if not path.exists():
        return readings
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 8 or not all(fields):
            continue
        try:
            readings.append(
                ResourceReading(
                    float(fields[0]),
                    int(fields[1]),
                    fields[2],
                    int(fields[3]),
                    int(fields[4]),
                    int(fields[5]),
                    int(fields[6]),
                    int(fields[7]),
                )
            )
        except ValueError:
            continue
    return readings


@dataclass(frozen=True)
class SmokeRun:
    arm: str
    run_directory: Path
    # <checkpoints>/<run>_phase_0001: phase.json and the adapters.
    phase_directory: Path
    readings: Path
    kill: Path | None = None


@dataclass(frozen=True)
class Check:
    name: str
    # False: a reading reported beside the gates, never failing the smoke test.
    gate: bool
    passed: bool
    detail: str


WAKE_PATTERN = re.compile(r"GPU (\d+) ([\d.]+) of ([\d.]+) GiB free, its servers' shares ([\d.]+) GiB")
OUT_OF_MEMORY_PATTERN = re.compile(r"out of memory|OutOfMemoryError", re.IGNORECASE)


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def gate(name: str, passed: bool, detail: str) -> Check:
    return Check(name, True, passed, detail)


def reading(name: str, detail: str) -> Check:
    return Check(name, False, True, detail)


def round_checks(run: SmokeRun, version: ModelVersion | None) -> list[Check]:
    rounds = metric_lines(run.run_directory, ExpertIterationPhase.family, ExpertIterationPhase, SMOKE_PHASES)
    checks = []
    if len(rounds) != 1:
        return [gate("round trained", False, f"{len(rounds)} expert_iteration lines for phase 1, not 1")]
    (record,) = rounds
    trained = (
        not record.skipped
        and record.optimizer_steps > 0
        and (record.parameter_change_norm or 0.0) > 0
        and record.lean_replay_examples > 0
        and record.math_replay_examples > 0
    )
    counts = (
        f"{record.examples:,} training examples from {record.solved_trees:,} solved trees, "
        f"{record.optimizer_steps} steps, LoRA change {record.parameter_change_norm}, replay "
        f"{record.lean_replay_examples} Lean and {record.math_replay_examples} math examples"
    )
    match record.skip:
        case RoundSkip.TOO_FEW_EXAMPLES:
            detail = f"skipped: too few examples for the loop's floor (expert_iteration_min_examples); {counts}"
        case RoundSkip.NO_OPTIMIZER_STEP:
            detail = f"skipped: its examples and replay fill no optimizer step; {counts}"
        case None:
            detail = f"one line; {counts}"
    checks.append(gate("round trained", trained, detail))
    adapter = "" if version is None else version.policy_adapter
    checks.append(
        gate(
            "round published",
            adapter.endswith("expert_iteration/adapter"),
            f"version 1's policy adapter {adapter or 'missing'}",
        )
    )
    checks.append(
        reading(
            "round duration",
            f"{record.training_seconds:.0f} s training, peak allocated {record.peak_memory_gib:.1f} GiB, "
            f"{record.trained_tokens:,} trained of {record.tokens:,} tokens",
        )
    )
    if run.arm == "D":
        grpo = metric_lines(run.run_directory, GrpoPhase.family, GrpoPhase, SMOKE_PHASES)
        whole = record.phase_parameter_change_norm or 0.0
        checks.append(
            gate(
                "GRPO then the round",
                len(grpo) == 1 and grpo[0].optimizer_steps > 0 and whole >= (record.parameter_change_norm or 0.0),
                f"{len(grpo)} grpo lines for phase 1"
                + (f", {grpo[0].optimizer_steps} GRPO steps" if grpo else "")
                + f"; the phase's LoRA change {whole} against the round's {record.parameter_change_norm}",
            )
        )
    return checks


def build_checks(run: SmokeRun, log: str) -> list[Check]:
    summary = run.run_directory / "expert_iteration" / f"phase_{SMOKE_PHASES:04d}" / "summary.json"
    built = re.search(rf"Expert-iteration round of phase {SMOKE_PHASES}, built in (\d+) s", log)
    return [
        gate("in-loop build", summary.exists(), f"{summary} {'exists' if summary.exists() else 'is missing'}"),
        reading("build duration", f"{built.group(1)} s" if built else "no build line in loop.log"),
    ]


def memory_checks(run: SmokeRun, log: str, trainer_log: str, readings: Sequence[ResourceReading]) -> list[Check]:
    checks = []
    out_of_memory = OUT_OF_MEMORY_PATTERN.findall(trainer_log)
    checks.append(
        gate("no out-of-memory", not out_of_memory, f"{len(out_of_memory)} out-of-memory lines in trainer.log")
    )
    training = [entry for entry in readings if entry.stage == "training" and entry.phase == SMOKE_PHASES]
    if not training:
        checks.append(reading("GPU memory while training", "no nvidia-smi reading in the training stage"))
    else:
        peaks = {
            gpu: max(entry.used_mib for entry in training if entry.gpu == gpu)
            for gpu in sorted({entry.gpu for entry in training})
        }
        total = max(entry.total_mib for entry in training)
        listed = ", ".join(f"GPU {gpu} {peak:,} MiB" for gpu, peak in peaks.items())
        checks.append(
            reading(
                "GPU memory while training",
                f"nvidia-smi peaks (reserved included) {listed} of {total:,} MiB; {len(training)} readings",
            )
        )
    wakes = [WAKE_PATTERN.findall(line) for line in log.splitlines() if "GPU memory before the wake" in line]
    if not wakes:
        checks.append(gate("GPU memory before the wake", False, "no 'GPU memory before the wake' line in loop.log"))
    else:
        last = wakes[-1]
        checks.append(
            gate(
                "GPU memory before the wake",
                bool(last) and all(float(free) >= float(shares) for _, free, _, shares in last),
                "; ".join(
                    f"GPU {gpu} {free} of {total} GiB free, shares {shares}" for gpu, free, total, shares in last
                ),
            )
        )
    if readings:
        peak = max(entry.shared_memory_used_kib for entry in readings)
        size = max(entry.shared_memory_size_kib for entry in readings)
        checks.append(
            gate(
                "/dev/shm",
                peak <= MAX_SHARED_MEMORY_SHARE * size,
                f"peak {peak / 2**20:.1f} of {size / 2**20:.1f} GiB (at most {MAX_SHARED_MEMORY_SHARE:.0%})",
            )
        )
    else:
        checks.append(gate("/dev/shm", False, "no reading"))
    outcome_path = run.phase_directory / "phase.json"
    if outcome_path.exists():
        outcome = read_phase_outcome(outcome_path)
        stages = ", ".join(
            f"{memory.stage} {memory.allocated_gib:.1f}/{memory.reserved_gib:.1f}" for memory in outcome.memory
        )
        checks.append(reading("trainer's memory after each stage (allocated/reserved GiB)", stages or "none recorded"))
        recompiles = trainer_log.count("hit config.recompile_limit")
        checks.append(
            reading(
                "recompiles",
                f"{outcome.timings.compiled_graphs} graphs compiled in the phase; {recompiles} 'recompile_limit' "
                "warnings in trainer.log (arm A's phase 1 hit it on all four ranks too)",
            )
        )
    return checks


def kill_checks(run: SmokeRun, kill: SmokeKill, log: str, version_count: int) -> list[Check]:
    starts = len(re.findall(rf"Loop {re.escape(run.run_directory.name)}: version", log))
    outcome = run.phase_directory / "phase.json"
    summary = run.run_directory / "expert_iteration" / f"phase_{SMOKE_PHASES:04d}" / "summary.json"
    records = read_json_lines(run.run_directory / "phases.jsonl", PhaseRecord)
    trained_before = outcome.exists() and outcome.stat().st_mtime < kill.killed_at
    built_before = summary.exists() and summary.stat().st_mtime < kill.killed_at
    return [
        gate(
            "killed while publishing",
            kill.stage == "publishing" and kill.phase == SMOKE_PHASES,
            f"pid {kill.pid} killed in phase {kill.phase}'s stage {kill.stage}, {kill.stage_seconds:.0f} s into it",
        ),
        gate("restarted", starts >= 2, f"{starts} loop starts in loop.log"),
        gate(
            "nothing trained or built again",
            trained_before and built_before,
            f"phase.json written before the kill: {trained_before}; the build's summary.json: {built_before}",
        ),
        gate(
            "one phase record and one version",
            sum(record.phase == SMOKE_PHASES for record in records) == 1 and version_count == 1,
            f"{sum(record.phase == SMOKE_PHASES for record in records)} phases.jsonl lines and {version_count} "
            "versions for phase 1",
        ),
    ]


def value_check(run_directory: Path, version: ModelVersion | None) -> Check:
    """The smoke's phase trains the value model beside the policy update (value_every_phases = 1)."""
    initial = next((record for record in read_versions(run_directory) if record.version == 0), None)
    published = version is not None and initial is not None and version.value_adapter != initial.value_adapter
    adapter = "missing" if version is None else version.value_adapter
    return gate("value model trained in the phase", published, f"version 1's value adapter {adapter}")


def smoke_checks(run: SmokeRun) -> list[Check]:
    """The smoke run's gates (any failing one fails the smoke test) and readings."""
    finished = read_finished(run.run_directory)
    stop = read_health_stop(run.run_directory)
    versions = [version for version in read_versions(run.run_directory) if version.trigger == phase_trigger(1)]
    checks = [
        gate(
            "finished",
            finished is not None and finished.last_phase == SMOKE_PHASES and stop is None,
            f"finished.json {'last phase ' + str(finished.last_phase) if finished else 'missing'}; "
            f"health_stop.json {'present' if stop else 'absent'}",
        ),
        gate("one version for the phase", len(versions) == 1, f"{len(versions)} versions published as phase 1"),
        value_check(run.run_directory, versions[0] if versions else None),
    ]
    log = text_of(run.run_directory / "loop.log")
    trainer_log = text_of(run.run_directory / "training" / "trainer.log")
    checks += round_checks(run, versions[0] if versions else None)
    checks += build_checks(run, log)
    checks += memory_checks(run, log, trainer_log, read_readings(run.readings))
    records = read_json_lines(run.run_directory / "phases.jsonl", PhaseRecord)
    for record in records:
        checks.append(
            reading(
                "phase durations",
                f"sampling {record.sampling_seconds / 60:.1f} min, training {record.training_seconds / 60:.1f} min, "
                f"publishing {record.publishing_seconds / 60:.1f} min, evaluation {record.evaluation_seconds / 60:.1f} "
                f"min; {record.trees} trees, {record.solved_trees} solved, {record.generated_tokens:,} tokens",
            )
        )
    if run.kill is not None:
        if not run.kill.exists():
            checks.append(gate("killed while publishing", False, f"no kill record {run.kill}"))
        else:
            kill = from_json_object(SmokeKill, json.loads(run.kill.read_text(encoding="utf-8")))
            checks += kill_checks(run, kill, log, len(versions))
    return checks


def smoke_report(results: Sequence[tuple[SmokeRun, Sequence[Check]]]) -> tuple[bool, str]:
    """Whether every gate passed, and the report."""
    passed = all(check.passed for _, checks in results for check in checks if check.gate)
    lines = [
        f"# Smoke test of expert iteration inside the loop: {'PASSED' if passed else 'FAILED'}",
        "",
        f"One phase of {SMOKE_PHASE_GENERATED_TOKENS:,} generated tokens per run, arms C and D under their own names "
        f"({', '.join(smoke_run_name(arm) for arm in SMOKE_ARMS)}); each phase trains the value model and a round "
        "(D: GRPO, the value model and a round in one trainer process, the heaviest pause C and D meet). Gates "
        "decide; readings are reported.",
        "",
        f"The kill: {smoke_run_name(SMOKE_KILLED_ARM)}'s loop was killed by PID (SIGKILL) about 30 s into publishing "
        'phase 1. With the servers restarted onto new weights (swap = "restart", about 135-250 s) that lands after '
        "the trainer handed off its merges and while the servers restart onto them, before the version is recorded: "
        "a restart serves version 0 from disk, then the handed-off version, and records it once. It is not review "
        "AS's M1 point (during the durable write itself). The driver stopped the servers before the restart; a real "
        "crash leaves them up, the common and easier case.",
        "",
    ]
    for run, checks in results:
        lines += [f"## {run.run_directory.name}", "", "| Check | Kind | Result | Detail |", "|---|---|---|---|"]
        for check in checks:
            result = ("PASS" if check.passed else "**FAIL**") if check.gate else "-"
            lines.append(f"| {check.name} | {'gate' if check.gate else 'reading'} | {result} | {check.detail} |")
        lines.append("")
    missed = any(
        check.name == "killed while publishing" and not check.passed for _, checks in results for check in checks
    )
    if missed:
        lines += [
            f"To repeat {smoke_run_name(SMOKE_KILLED_ARM)}: move `runs/{smoke_run_name(SMOKE_KILLED_ARM)}`, "
            f"`runs/followup_configs/{smoke_run_name(SMOKE_KILLED_ARM)}` and "
            f"`checkpoints/{smoke_run_name(SMOKE_KILLED_ARM)}*` aside; in the chain's state delete "
            f"`done_loop_smoke_{SMOKE_KILLED_ARM}`, `attempts_loop_smoke_{SMOKE_KILLED_ARM}_start`, "
            f"`smoke/kill_{SMOKE_KILLED_ARM}.json`, `smoke/restarted_{SMOKE_KILLED_ARM}` and "
            f"`smoke/readings_{SMOKE_KILLED_ARM}.tsv`; rename STOPPED and start arms_chain.",
            "",
        ]
    lines += [
        "Not covered by the smoke test, so passing it does not clear reviews AS's and AT's whole lists: the build and "
        "round on a full 4-phase window (watch arm C's phase 4: the hand-run round built 2,947 trees in about 80 s); a "
        "kill during the build, and of one trainer rank during the round (AS 5); a stop during a build (AT 6); the "
        "in-loop round against the hand-run `train` (AS 2; the CPU tests compare them); exactly one policy merge in "
        "/dev/shm's handoff (AT 1: only implied by the published adapter's path and the /dev/shm peak).",
        "",
    ]
    return passed, "\n".join(lines)
