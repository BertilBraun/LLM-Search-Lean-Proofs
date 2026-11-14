"""Compute, throughput and hardware use of grpo_loop_v1 from its published run logs, for sizing a follow-up run.

    PYTHONPATH=src python experiments/analysis/throughput_and_hardware.py \
        [--metrics node_backup/2026-11-01/hf_run/run_logs/metrics] \
        [--evaluations node_backup/2026-11-01/hf_dataset/evaluations/evaluations.jsonl] \
        [--output results/followup_step0]

Prints markdown tables and writes phases.csv and versions.csv to the output directory. Generated tokens of the training
searches are not in the metrics (only for the search-options A/B phases): they are estimated as expansions times the
tokens per expansion of the probe run nearest in time, and checked against the A/B phases.
"""

import argparse
import bisect
import csv
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import astuple, dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

GPUS = 4
HOURLY_PRICE = 0.965
# The write-up's rental window; the run logs start ~20 h later (bring-up) and end ~1 h earlier (backup).
NODE_RENTED_AT = datetime(2026, 10, 29, 15, 30, tzinfo=UTC).timestamp()
NODE_RELEASED_AT = datetime(2026, 11, 1, 23, 0, tzinfo=UTC).timestamp()
ELO_PER_LOGIT = 400 / math.log(10)
SEARCH_CONCURRENCY = 112
PROBE_PROBLEMS = 501
# The write-up's rejected versions 5-10 (rejected_versions.jsonl is not in the logs; the rating flags only rated ones).
FIRST_REJECTED_VERSION = 5
# From this phase on the CPU quota throttled the node during sampling (12% or more of the periods, see phases.csv).
FIRST_CPU_BOUND_PHASE = 13
# Phases whose search-options A/B recorded the generated tokens of (nearly) all their trees.
MIN_RECORDED_TREE_SHARE = 0.95


class Activity(StrEnum):
    BASELINE_EVALUATION = "v0 baselines (no sampling)"
    SAMPLING = "sampling"
    SAMPLING_WITH_EVALUATION = "sampling + probe/miniF2F beside"
    TRAINING_PAUSE = "pause: training + publish"
    PAUSE_EVALUATION = "pause: held-out states"
    EXPERT_ITERATION = "expert-iteration round (loop stopped)"
    EVALUATION_LOOP_STOPPED = "evaluation, loop stopped"
    STOPPED = "stopped / restarts"


class Group(StrEnum):
    SAMPLING = "sampling"
    TRAINING = "training"
    OTHER = "other"


GROUP_OF_ACTIVITY = {
    Activity.BASELINE_EVALUATION: Group.OTHER,
    Activity.SAMPLING: Group.SAMPLING,
    Activity.SAMPLING_WITH_EVALUATION: Group.SAMPLING,
    Activity.TRAINING_PAUSE: Group.TRAINING,
    Activity.PAUSE_EVALUATION: Group.OTHER,
    Activity.EXPERT_ITERATION: Group.TRAINING,
    Activity.EVALUATION_LOOP_STOPPED: Group.OTHER,
    Activity.STOPPED: Group.OTHER,
}


@dataclass(frozen=True)
class StatusRecord:
    time: float
    state: str
    phase: int
    policy_version: int


@dataclass(frozen=True)
class SystemSample:
    time: float
    seconds: float
    gpu_utilization: tuple[float, ...]
    gpu_memory_used_gib: tuple[float, ...]
    gpu_memory_total_gib: tuple[float, ...]
    gpu_power_watts: tuple[float, ...]
    cpu_cores_used: float
    cpu_cores_available: float
    lean_cores_used: float
    cpu_throttled_fraction: float
    memory_used_gib: float
    memory_total_gib: float
    memory_available_gib: float
    lean_processes: int
    lean_private_memory_gib: float
    lean_private_memory_p90_gib: float
    vllm_private_memory_gib: float
    disk_total_gib: float
    disk_free_gib: float


@dataclass(frozen=True)
class EvaluationRun:
    kind: str
    run_name: str
    policy_version: int
    problems: int
    solved: int
    expansions: int
    generated_tokens: int
    lean_seconds: float
    wall_seconds: float
    started: float
    finished: float
    part: int | None

    @property
    def tokens_per_expansion(self) -> float:
        return self.generated_tokens / self.expansions


@dataclass(frozen=True)
class PhaseRecord:
    phase: int
    sampling_policy_version: int
    published_at: float
    sampling_seconds: float
    pause_seconds: float
    drain_seconds: float
    scoring_seconds: float
    policy_training_seconds: float
    value_training_seconds: float
    other_training_seconds: float
    publish_and_wake_seconds: float
    held_out_seconds: float
    trees: int
    solved_trees: int
    trainable_groups: int
    expansions: int
    lean_seconds: float
    trained_tokens: int
    recorded_generated_tokens: int | None
    estimated_generated_tokens: float
    evaluation_tokens_beside: float
    evaluation_expansions_beside: float
    mean_gpu_utilization: float
    mean_gpu_power_watts: float
    mean_cpu_cores_used: float
    mean_lean_cores_used: float
    mean_cpu_throttled_fraction: float

    @property
    def pause_overhead_seconds(self) -> float:
        return self.other_training_seconds + self.drain_seconds + self.publish_and_wake_seconds

    @property
    def lean_core_seconds(self) -> float:
        return self.mean_lean_cores_used * self.sampling_seconds

    @property
    def all_expansions(self) -> float:
        return self.expansions + self.evaluation_expansions_beside

    @property
    def lean_share_of_search_time(self) -> float:
        return self.lean_seconds / (SEARCH_CONCURRENCY * self.sampling_seconds)

    @property
    def tokens_per_gpu_second(self) -> float:
        return (self.estimated_generated_tokens + self.evaluation_tokens_beside) / (GPUS * self.sampling_seconds)


@dataclass(frozen=True)
class VersionRating:
    policy_version: int
    value_version: int
    problems: int
    solved: int
    rejected: bool
    rating_logits: float
    lower_logits: float
    upper_logits: float
    solved_within: tuple[float, ...]
    baseline_solved_within: tuple[float, ...]


@dataclass(frozen=True)
class PassRating:
    time: float
    policy_versions: tuple[int, ...]
    rating_logits: float
    lower_logits: float
    upper_logits: float
    projected_solved: float
    baseline_projected_solved: float


@dataclass(frozen=True)
class ActivityTotals:
    seconds: dict[Activity, float]

    def group_hours(self, group: Group) -> float:
        return sum(seconds for activity, seconds in self.seconds.items() if GROUP_OF_ACTIVITY[activity] == group) / 3600

    @property
    def hours(self) -> float:
        return sum(self.seconds.values()) / 3600


@dataclass(frozen=True)
class VersionCompute:
    rating: VersionRating
    part: int
    published_at: float
    totals: ActivityTotals
    lineage_hours: float
    trees: int
    expansions: int
    estimated_tokens: float


def records(path: Path) -> Iterator[dict]:
    with path.open() as lines:
        for line in lines:
            yield json.loads(line)


def read_status(metrics: Path) -> list[StatusRecord]:
    return [
        StatusRecord(record["time"], record["fields"]["state"], record["phase"], record["policy_version"])
        for record in records(metrics / "status.jsonl")
    ]


def read_system(metrics: Path) -> list[SystemSample]:
    samples = []
    previous_time = None
    for record in records(metrics / "system.jsonl"):
        values = record["fields"]
        time = record["time"]
        samples.append(
            SystemSample(
                time=time,
                seconds=0.0 if previous_time is None else time - previous_time,
                gpu_utilization=tuple(values["gpu_utilization"]),
                gpu_memory_used_gib=tuple(values["gpu_memory_used_gib"]),
                gpu_memory_total_gib=tuple(values["gpu_memory_total_gib"]),
                gpu_power_watts=tuple(values["gpu_power_watts"]),
                cpu_cores_used=values["cpu_cores_used"],
                cpu_cores_available=values["cpu_cores_available"],
                lean_cores_used=values["lean_cores_used"],
                cpu_throttled_fraction=values["cpu_throttled_fraction"],
                memory_used_gib=values["memory_used_gib"],
                memory_total_gib=values["memory_total_gib"],
                memory_available_gib=values["memory_available_gib"],
                lean_processes=values["lean_processes"],
                lean_private_memory_gib=values["lean_private_memory_gib"],
                lean_private_memory_p90_gib=values["lean_private_memory_p90_gib"],
                vllm_private_memory_gib=values["vllm_private_memory_gib"],
                disk_total_gib=values["disk_total_gib"],
                disk_free_gib=values["disk_free_gib"],
            )
        )
        previous_time = time
    return samples


def read_evaluations(path: Path) -> list[EvaluationRun]:
    return [
        EvaluationRun(
            kind=record["kind"],
            run_name=record["run_name"],
            policy_version=record["policy_version"],
            problems=record["problems"],
            solved=record["solved"],
            expansions=record["expansions"],
            generated_tokens=record["generated_tokens"],
            lean_seconds=record["lean_seconds"],
            wall_seconds=record["wall_seconds"],
            started=datetime.fromisoformat(record["started_at"]).timestamp(),
            finished=datetime.fromisoformat(record["finished_at"]).timestamp(),
            part=record["part"],
        )
        for record in records(path)
    ]


def read_ratings(metrics: Path) -> tuple[list[VersionRating], list[PassRating]]:
    lines = list(records(metrics / "rating.jsonl"))
    passes: dict[tuple[int, ...], PassRating] = {}
    for line in lines:
        latest = line["fields"]["latest_pass"]
        versions = tuple(latest["policy_versions"])
        if versions not in passes:
            passes[versions] = PassRating(
                line["time"],
                versions,
                latest["rating"],
                latest["lower"],
                latest["upper"],
                latest["projected_solved"],
                line["fields"]["baseline_projected_solved"],
            )
    versions = [
        VersionRating(
            policy_version=version["policy_version"],
            value_version=version["value_version"],
            problems=version["problems"],
            solved=version["solved"],
            rejected=version["rejected"],
            rating_logits=version["rating"],
            lower_logits=version["lower"],
            upper_logits=version["upper"],
            solved_within=tuple(version["solved_within"]),
            baseline_solved_within=tuple(version["baseline_solved_within"]),
        )
        for version in lines[-1]["fields"]["versions"]
    ]
    return versions, list(passes.values())


def by_phase(metrics: Path, family: str) -> dict[int, dict]:
    return {record["phase"]: record for record in records(metrics / f"{family}.jsonl")}


class Timeline:
    def __init__(self, status: list[StatusRecord], evaluations: list[EvaluationRun]) -> None:
        self.status = status
        self.times = [record.time for record in status]
        self.evaluations = evaluations
        self.loop_started_at = next(record.time for record in status if record.state == "searching")
        loop_versions = {record.policy_version for record in status}
        outside_loop = [run for run in evaluations if run.policy_version not in loop_versions]
        self.expert_iteration_window = (
            self.status_at(min(run.started for run in outside_loop)).time,
            self.status[bisect.bisect_right(self.times, max(run.finished for run in outside_loop))].time,
        )

    def status_at(self, time: float) -> StatusRecord:
        return self.status[max(bisect.bisect_right(self.times, time) - 1, 0)]

    def evaluation_running(self, time: float) -> bool:
        return any(run.started <= time < run.finished for run in self.evaluations)

    def activity(self, time: float) -> Activity:
        match self.status_at(time).state:
            case "searching":
                return Activity.SAMPLING_WITH_EVALUATION if self.evaluation_running(time) else Activity.SAMPLING
            case "paused" | "training" | "publishing":
                return Activity.TRAINING_PAUSE
            case "evaluating" if time < self.loop_started_at:
                return Activity.BASELINE_EVALUATION
            case "evaluating":
                return Activity.PAUSE_EVALUATION
            case "stopped" if self.expert_iteration_window[0] <= time < self.expert_iteration_window[1]:
                return Activity.EXPERT_ITERATION
            case "stopped" if self.evaluation_running(time):
                return Activity.EVALUATION_LOOP_STOPPED
            case _:
                return Activity.STOPPED

    def first_time(self, state: str | None, phase: int | None = None, policy_version: int | None = None) -> float:
        return next(
            record.time
            for record in self.status
            if (state is None or record.state == state)
            and (phase is None or record.phase == phase)
            and (policy_version is None or record.policy_version == policy_version)
        )


def activity_totals(samples: Sequence[SystemSample], activities: Sequence[Activity], until: float) -> ActivityTotals:
    seconds: dict[Activity, float] = defaultdict(float)
    for sample, activity in zip(samples, activities, strict=True):
        if sample.time <= until:
            seconds[activity] += sample.seconds
    return ActivityTotals(dict(seconds))


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(share * len(ordered)), len(ordered) - 1)]


def nearest_probe(probes: Sequence[EvaluationRun], time: float) -> EvaluationRun:
    return min(probes, key=lambda run: abs((run.started + run.finished) / 2 - time))


def overlap_share(run: EvaluationRun, start: float, end: float) -> float:
    return max(0.0, min(run.finished, end) - max(run.started, start)) / (run.finished - run.started)


def build_phases(
    metrics: Path,
    timeline: Timeline,
    samples: Sequence[SystemSample],
    activities: Sequence[Activity],
    evaluations: Sequence[EvaluationRun],
) -> list[PhaseRecord]:
    timing = by_phase(metrics, "timing")
    budget = by_phase(metrics, "budget")
    search = by_phase(metrics, "search")
    grpo = by_phase(metrics, "grpo")
    probes = [run for run in evaluations if run.kind == "probe"]
    beside = [run for run in evaluations if run.kind in ("probe", "minif2f") and run.started > timeline.loop_started_at]
    sample_times = [sample.time for sample in samples]
    phases = []
    for phase, record in sorted(timing.items()):
        values = record["fields"]
        pause = values["pause"]
        sampling_start = timeline.first_time("searching", phase=phase)
        sampling_end = timeline.first_time("paused", phase=phase)
        searched = search[phase]["fields"]
        budget_values = budget[phase]["fields"]
        arms = budget_values.get("by_search_arm") or {}
        recorded_trees = sum(arm["trees"] for arm in arms.values())
        recorded_tokens = (
            sum(arm["generated_tokens"] for arm in arms.values())
            if recorded_trees >= MIN_RECORDED_TREE_SHARE * budget_values["trees"]
            else None
        )
        probe = nearest_probe(probes, (sampling_start + sampling_end) / 2)
        window = [
            sample
            for sample, activity in zip(
                samples[
                    bisect.bisect_left(sample_times, sampling_start) : bisect.bisect_left(sample_times, sampling_end)
                ],
                activities[
                    bisect.bisect_left(sample_times, sampling_start) : bisect.bisect_left(sample_times, sampling_end)
                ],
                strict=True,
            )
            if GROUP_OF_ACTIVITY[activity] == Group.SAMPLING
        ]
        training = values["training_seconds"]
        trained_parts = pause["scoring_seconds"] + pause["policy_training_seconds"] + pause["value_training_seconds"]
        pause_start = timeline.first_time("paused", phase=phase)
        pause_end = next(
            status.time for status in timeline.status if status.time > pause_start and status.state == "searching"
        )
        phases.append(
            PhaseRecord(
                phase=phase,
                sampling_policy_version=record["policy_version"],
                published_at=record["time"],
                sampling_seconds=values["sampling_seconds"],
                pause_seconds=pause_end - pause_start,
                drain_seconds=pause["drain_seconds"] + pause["server_sleep_seconds"],
                scoring_seconds=pause["scoring_seconds"],
                policy_training_seconds=pause["policy_training_seconds"],
                value_training_seconds=pause["value_training_seconds"],
                other_training_seconds=training - trained_parts,
                publish_and_wake_seconds=values["publishing_seconds"] + pause["wake_seconds"],
                held_out_seconds=values["evaluation_seconds"],
                trees=budget_values["trees"],
                solved_trees=budget_values["solved_trees"],
                trainable_groups=budget_values["trainable_groups"],
                expansions=searched["expansions"],
                lean_seconds=searched["lean_seconds"],
                trained_tokens=grpo[phase]["fields"]["trained_tokens"],
                recorded_generated_tokens=recorded_tokens,
                estimated_generated_tokens=searched["expansions"] * probe.tokens_per_expansion,
                evaluation_tokens_beside=sum(
                    run.generated_tokens * overlap_share(run, sampling_start, sampling_end) for run in beside
                ),
                evaluation_expansions_beside=sum(
                    run.expansions * overlap_share(run, sampling_start, sampling_end) for run in beside
                ),
                mean_gpu_utilization=mean([mean(sample.gpu_utilization) for sample in window]),
                mean_gpu_power_watts=mean([mean(sample.gpu_power_watts) for sample in window]),
                mean_cpu_cores_used=mean([sample.cpu_cores_used for sample in window]),
                mean_lean_cores_used=mean([sample.lean_cores_used for sample in window]),
                mean_cpu_throttled_fraction=mean([sample.cpu_throttled_fraction for sample in window]),
            )
        )
    return phases


def format_hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f}"


def print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    print("| " + " | ".join(headers) + " |")
    print("|" + "---|" * len(headers))
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")
    print()


def report_activities(totals: ActivityTotals, logged_start: float, logged_end: float) -> None:
    before = logged_start - NODE_RENTED_AT
    after = NODE_RELEASED_AT - logged_end
    node_seconds = NODE_RELEASED_AT - NODE_RENTED_AT
    rows = [["bring-up before the logs (not logged)", format_hours(before), f"{before / node_seconds:.0%}"]]
    rows += [
        [activity.value, format_hours(seconds), f"{seconds / node_seconds:.0%}"]
        for activity, seconds in sorted(totals.seconds.items(), key=lambda item: -item[1])
    ]
    rows.append(["after the logs, to release (not logged)", format_hours(after), f"{after / node_seconds:.0%}"])
    rows.append(["node total", format_hours(node_seconds), f"${node_seconds / 3600 * HOURLY_PRICE:.0f}"])
    print("## Wall clock by activity (hours, share of the rented node)\n")
    print_table(["activity", "hours", "share"], rows)


def report_hardware(samples: Sequence[SystemSample], activities: Sequence[Activity]) -> None:
    grouped: dict[Activity, list[SystemSample]] = defaultdict(list)
    for sample, activity in zip(samples, activities, strict=True):
        grouped[activity].append(sample)
    rows = []
    for activity, members in sorted(grouped.items(), key=lambda item: -len(item[1])):
        utilization = [mean(sample.gpu_utilization) for sample in members]
        busiest_memory = [max(sample.gpu_memory_used_gib) for sample in members]
        rows.append(
            [
                activity.value,
                len(members),
                f"{mean(utilization):.0f} ({percentile(utilization, 0.1):.0f}/{percentile(utilization, 0.9):.0f})",
                f"{mean([mean(sample.gpu_power_watts) for sample in members]):.0f}",
                f"{statistics.median(busiest_memory):.1f} / {max(busiest_memory):.1f}",
                f"{mean([sample.cpu_cores_used for sample in members]):.0f} / "
                f"{percentile([sample.cpu_cores_used for sample in members], 0.9):.0f} / "
                f"{max(sample.cpu_cores_used for sample in members):.0f}",
                f"{mean([sample.lean_cores_used for sample in members]):.0f} / "
                f"{percentile([sample.lean_cores_used for sample in members], 0.9):.0f}",
                f"{mean([sample.lean_processes for sample in members]):.0f}",
                f"{mean([sample.memory_used_gib for sample in members]):.0f} / "
                f"{max(sample.memory_used_gib for sample in members):.0f}",
                f"{min(sample.memory_available_gib for sample in members):.0f}",
                f"{max(sample.lean_private_memory_gib for sample in members):.0f}",
                f"{max(sample.vllm_private_memory_gib for sample in members):.0f}",
                f"{mean([sample.cpu_throttled_fraction for sample in members]):.2f}",
            ]
        )
    first = samples[0]
    print(
        f"## Hardware by activity (node: {len(first.gpu_utilization)} GPUs x {max(first.gpu_memory_total_gib)} GiB, "
        f"{first.cpu_cores_available:.1f} cores available, {first.memory_total_gib:.0f} GiB RAM limit, "
        f"{first.disk_total_gib:.0f} GiB disk, min free {min(sample.disk_free_gib for sample in samples):.0f} GiB)\n"
    )
    print_table(
        [
            "activity",
            "samples",
            "GPU util % mean (p10/p90)",
            "GPU W",
            "busiest GPU mem GiB p50/max",
            "CPU cores mean/p90/max",
            "Lean cores mean/p90",
            "REPLs",
            "RAM GiB mean/max",
            "RAM avail min",
            "Lean priv max",
            "vLLM priv max",
            "throttled share",
        ],
        rows,
    )


def report_phases(phases: Sequence[PhaseRecord]) -> None:
    print("## Phases\n")
    print_table(
        [
            "phase",
            "sampled by",
            "sampling min",
            "pause min",
            "scoring",
            "policy",
            "value",
            "other",
            "trees",
            "groups",
            "expansions",
            "tokens M (est)",
            "tokens M (recorded)",
            "eval tokens M beside",
            "tok/s/GPU",
            "Lean share",
            "GPU util",
            "GPU W",
            "CPU cores",
            "Lean cores",
            "throttled",
        ],
        [
            [
                phase.phase,
                phase.sampling_policy_version,
                f"{phase.sampling_seconds / 60:.0f}",
                f"{phase.pause_seconds / 60:.1f}",
                f"{phase.scoring_seconds / 60:.1f}",
                f"{phase.policy_training_seconds / 60:.1f}",
                f"{phase.value_training_seconds / 60:.1f}",
                f"{phase.pause_overhead_seconds / 60:.1f}",
                phase.trees,
                phase.trainable_groups,
                phase.expansions,
                f"{phase.estimated_generated_tokens / 1e6:.1f}",
                "" if phase.recorded_generated_tokens is None else f"{phase.recorded_generated_tokens / 1e6:.1f}",
                f"{phase.evaluation_tokens_beside / 1e6:.1f}",
                f"{phase.tokens_per_gpu_second:.0f}",
                f"{phase.lean_share_of_search_time:.2f}",
                f"{phase.mean_gpu_utilization:.0f}",
                f"{phase.mean_gpu_power_watts:.0f}",
                f"{phase.mean_cpu_cores_used:.0f}",
                f"{phase.mean_lean_cores_used:.0f}",
                f"{phase.mean_cpu_throttled_fraction:.2f}",
            ]
            for phase in phases
        ],
    )
    regular = [phase for phase in phases if phase.sampling_seconds > 70 * 60]
    for label, members in (
        ("policy-only pauses", [phase for phase in regular if phase.value_training_seconds == 0]),
        ("policy+value pauses", [phase for phase in regular if phase.value_training_seconds > 0]),
    ):
        print(
            f"- {label} ({len(members)} phases of 75 min): pause median "
            f"{statistics.median(phase.pause_seconds for phase in members) / 60:.1f} min; scoring "
            f"{statistics.median(phase.scoring_seconds for phase in members) / 60:.1f}, policy "
            f"{statistics.median(phase.policy_training_seconds for phase in members) / 60:.1f}, value "
            f"{statistics.median(phase.value_training_seconds for phase in members) / 60:.1f}, rest "
            f"{statistics.median(phase.pause_overhead_seconds for phase in members) / 60:.1f}; "
            f"held-out after the pause {statistics.median(phase.held_out_seconds for phase in members) / 60:.1f}"
        )
    unthrottled = [phase for phase in phases if phase.phase < FIRST_CPU_BOUND_PHASE]
    throttled = [phase for phase in phases if phase.phase >= FIRST_CPU_BOUND_PHASE]
    for label, members in (
        (f"phases 1-{FIRST_CPU_BOUND_PHASE - 1}", unthrottled),
        (f"phases {FIRST_CPU_BOUND_PHASE}-30", throttled),
    ):
        sampling_seconds = sum(phase.sampling_seconds for phase in members)
        expansions = sum(phase.all_expansions for phase in members)
        tokens = sum(phase.estimated_generated_tokens + phase.evaluation_tokens_beside for phase in members)
        print(
            f"- {label}: median trees {statistics.median(phase.trees for phase in members):.0f}, groups "
            f"{statistics.median(phase.trainable_groups for phase in members):.0f}, expansions "
            f"{statistics.median(phase.expansions for phase in members):.0f}, est. tokens "
            f"{statistics.median(phase.estimated_generated_tokens for phase in members) / 1e6:.1f}M per phase; "
            f"pooled: {tokens / sampling_seconds / GPUS:.0f} tok/s/GPU, {expansions / sampling_seconds:.2f} "
            f"expansions/s, {tokens / expansions:.0f} tokens and "
            f"{sum(phase.lean_core_seconds for phase in members) / expansions:.0f} Lean core-seconds per expansion, "
            f"Lean share of search time {statistics.median(phase.lean_share_of_search_time for phase in members):.2f}, "
            f"throttled {mean([phase.mean_cpu_throttled_fraction for phase in members]):.2f}, GPU util "
            f"{statistics.median(phase.mean_gpu_utilization for phase in members):.0f}%"
        )
    for label, members in (
        (f"phases 1-{FIRST_CPU_BOUND_PHASE - 1}", unthrottled),
        (f"phases {FIRST_CPU_BOUND_PHASE}-30", throttled),
    ):
        alone = [phase for phase in members if phase.evaluation_expansions_beside == 0]
        expansions = sum(phase.expansions for phase in alone)
        slot_seconds = SEARCH_CONCURRENCY * sum(phase.sampling_seconds for phase in alone) / expansions
        lean_seconds = sum(phase.lean_seconds for phase in alone) / expansions
        print(
            f"- {label}, the {len(alone)} phases without evaluations beside: a search spends {slot_seconds:.0f} s "
            f"per expansion, {lean_seconds:.0f} s of it in Lean and {slot_seconds - lean_seconds:.0f} s waiting "
            "on the policy and value servers"
        )
    checked = [phase for phase in phases if phase.recorded_generated_tokens is not None]
    for phase in checked:
        print(
            f"- token estimate check, phase {phase.phase}: estimated {phase.estimated_generated_tokens / 1e6:.1f}M, "
            f"recorded {phase.recorded_generated_tokens / 1e6:.1f}M"
        )
    print()


def build_versions(
    ratings: Sequence[VersionRating],
    evaluations: Sequence[EvaluationRun],
    timeline: Timeline,
    samples: Sequence[SystemSample],
    activities: Sequence[Activity],
    phases: Sequence[PhaseRecord],
) -> list[VersionCompute]:
    rejected_start = timeline.first_time(None, phase=FIRST_REJECTED_VERSION)
    rejected_end = timeline.first_time(
        None, policy_version=max(rating.policy_version for rating in ratings if rating.rejected) + 1
    )
    rejected_seconds = sum(sample.seconds for sample in samples if rejected_start <= sample.time < rejected_end)
    computes = []
    for rating in ratings:
        probe = next(
            run
            for run in evaluations
            if run.kind == "probe" and run.policy_version == rating.policy_version and "repeat" not in run.run_name
        )
        published_at = (
            timeline.loop_started_at
            if rating.policy_version == 0
            else timeline.first_time(None, policy_version=rating.policy_version)
        )
        totals = activity_totals(samples, activities, published_at)
        trained_on = [phase for phase in phases if phase.published_at <= published_at + 60]
        on_lineage = rating.policy_version >= timeline.status_at(rejected_end).policy_version
        computes.append(
            VersionCompute(
                rating=rating,
                part=probe.part,
                published_at=published_at,
                totals=totals,
                lineage_hours=totals.hours - (rejected_seconds / 3600 if on_lineage else 0.0),
                trees=sum(phase.trees for phase in trained_on),
                expansions=sum(phase.expansions for phase in trained_on),
                estimated_tokens=sum(phase.estimated_generated_tokens for phase in trained_on),
            )
        )
    return computes


def report_versions(computes: Sequence[VersionCompute], logged_start: float) -> None:
    before_hours = (logged_start - NODE_RENTED_AT) / 3600
    print(
        f"## Versions (hours since the logs start; add {before_hours:.1f} h of unlogged bring-up for node time; "
        "GPU-h = 4 x wall)\n"
    )
    rows = []
    for compute in computes:
        rating = compute.rating
        points = 100 * (rating.solved_within[-1] - rating.baseline_solved_within[-1])
        rows.append(
            [
                f"v{rating.policy_version}" + (" (rejected)" if rating.rejected else ""),
                datetime.fromtimestamp(compute.published_at, UTC).strftime("%m-%d %H:%M"),
                f"{compute.totals.hours:.1f}",
                f"{GPUS * compute.totals.group_hours(Group.SAMPLING):.0f}",
                f"{GPUS * compute.totals.group_hours(Group.TRAINING):.0f}",
                f"{GPUS * compute.totals.group_hours(Group.OTHER):.0f}",
                f"{GPUS * compute.totals.hours:.0f}",
                f"{GPUS * compute.lineage_hours:.0f}",
                compute.trees,
                compute.expansions,
                f"{compute.estimated_tokens / 1e6:.0f}",
                compute.part,
                f"{rating.solved}/{rating.problems}",
                f"{100 * rating.solved_within[-1]:.1f} vs {100 * rating.baseline_solved_within[-1]:.1f}",
                f"{points:+.1f}",
                f"{100 * (rating.solved_within[2] - rating.baseline_solved_within[2]):+.1f}",
                f"{ELO_PER_LOGIT * rating.rating_logits:+.0f} "
                f"[{ELO_PER_LOGIT * rating.lower_logits:+.0f}, {ELO_PER_LOGIT * rating.upper_logits:+.0f}]",
            ]
        )
    print_table(
        [
            "version",
            "published",
            "wall h",
            "GPU-h sampling",
            "GPU-h training",
            "GPU-h other",
            "GPU-h total",
            "GPU-h lineage",
            "trees",
            "expansions",
            "tokens M (est)",
            "third",
            "solved",
            "% at 16 vs v0",
            "points at 16",
            "points at 4",
            "Elo [95%]",
        ],
        rows,
    )


def report_passes(
    passes: Sequence[PassRating], samples: Sequence[SystemSample], activities: Sequence[Activity]
) -> None:
    print("## Pooled passes (each line's own fit; v0 = 0)\n")
    rows = []
    for pass_rating in passes:
        totals = activity_totals(samples, activities, pass_rating.time)
        rows.append(
            [
                ", ".join(f"v{version}" for version in pass_rating.policy_versions),
                datetime.fromtimestamp(pass_rating.time, UTC).strftime("%m-%d %H:%M"),
                f"{GPUS * totals.hours:.0f}",
                f"{ELO_PER_LOGIT * pass_rating.rating_logits:+.0f} "
                f"[{ELO_PER_LOGIT * pass_rating.lower_logits:+.0f}, {ELO_PER_LOGIT * pass_rating.upper_logits:+.0f}]",
                f"{pass_rating.projected_solved:.0f} vs {pass_rating.baseline_projected_solved:.0f}",
                f"{100 * (pass_rating.projected_solved - pass_rating.baseline_projected_solved) / PROBE_PROBLEMS:+.1f}",
            ]
        )
    print_table(["pass", "rated at", "GPU-h so far", "Elo [95%]", "projected solved of 501 vs v0", "points"], rows)


def report_costs(
    phases: Sequence[PhaseRecord],
    evaluations: Sequence[EvaluationRun],
    totals: ActivityTotals,
    timeline: Timeline,
) -> None:
    node_hours = (NODE_RELEASED_AT - NODE_RENTED_AT) / 3600
    sampling_hours = totals.group_hours(Group.SAMPLING)
    tree_tokens = sum(phase.estimated_generated_tokens for phase in phases)
    beside_tokens = sum(phase.evaluation_tokens_beside for phase in phases)
    all_tokens = tree_tokens + sum(run.generated_tokens for run in evaluations)
    trees = sum(phase.trees for phase in phases)
    sampling_tokens_per_hour = (tree_tokens + beside_tokens) / sampling_hours
    print(f"## Cost per unit at ${HOURLY_PRICE:.3f}/h\n")
    print_table(
        ["basis", "hours", "tokens M", "trees", "$ per M tokens", "$ per 1,000 trees"],
        [
            [
                "whole rental (all overheads)",
                f"{node_hours:.1f}",
                f"{all_tokens / 1e6:.0f}",
                trees,
                f"{node_hours * HOURLY_PRICE / all_tokens * 1e6:.2f}",
                f"{node_hours * HOURLY_PRICE / trees * 1e3:.2f}",
            ],
            [
                "sampling hours only",
                f"{sampling_hours:.1f}",
                f"{(tree_tokens + beside_tokens) / 1e6:.0f}",
                trees,
                f"{HOURLY_PRICE / sampling_tokens_per_hour * 1e6:.2f}",
                f"{sampling_hours * HOURLY_PRICE / trees * 1e3:.2f}",
            ],
        ],
    )
    baseline = [run for run in evaluations if run.started < timeline.loop_started_at]
    baseline_hours = (max(run.finished for run in baseline) - min(run.started for run in baseline)) / 3600
    baseline_tokens = sum(run.generated_tokens for run in baseline)
    baseline_tokens_per_hour = baseline_tokens / baseline_hours
    probes = [run for run in evaluations if run.kind == "probe" and run.started > timeline.loop_started_at]
    tokens_per_problem = sum(run.generated_tokens for run in probes) / sum(run.problems for run in probes)
    print(
        f"- v0 baselines alone on the node: {baseline_tokens / 1e6:.1f}M tokens in {baseline_hours:.2f} h = "
        f"{baseline_tokens_per_hour / GPUS / 3600:.0f} tok/s/GPU; sampling phases: "
        f"{sampling_tokens_per_hour / GPUS / 3600:.0f} tok/s/GPU"
    )
    print(
        f"- probe runs beside sampling: {len(probes)} runs, median wall "
        f"{statistics.median(run.wall_seconds for run in probes) / 60:.0f} min per third, "
        f"{statistics.median(run.expansions / run.problems for run in probes):.1f} expansions and "
        f"{tokens_per_problem:.0f} tokens per statement, "
        f"{statistics.median(run.lean_seconds / run.wall_seconds for run in probes):.1f} Lean-seconds per wall second"
    )
    for label, tokens_per_hour in (
        ("sampling-phase throughput", sampling_tokens_per_hour),
        ("baseline (eval alone) throughput", baseline_tokens_per_hour),
    ):
        per_thousand = 1000 * tokens_per_problem / tokens_per_hour * HOURLY_PRICE
        print(
            f"- 1,000 statements at 16 expansions by token share at {label}: "
            f"{1000 * tokens_per_problem / tokens_per_hour:.2f} node-h, ${per_thousand:.2f}"
        )
    print(
        f"- wall-clock upper bound for one third beside sampling: "
        f"${statistics.median(run.wall_seconds for run in probes) / 3600 * HOURLY_PRICE:.2f} "
        "(the node also sampled meanwhile)"
    )
    for run in evaluations:
        if run.kind == "minif2f":
            print(
                f"- {run.run_name}: {run.problems} problems at 64 expansions, {run.expansions} expansions, "
                f"{run.generated_tokens / 1e6:.1f}M tokens, {run.wall_seconds / 3600:.2f} h wall, "
                f"Lean-seconds per wall second {run.lean_seconds / run.wall_seconds:.1f}"
            )
    print()


def report_probe_noise_and_cadence(evaluations: Sequence[EvaluationRun], loop_started_at: float) -> None:
    baselines: dict[int, list[EvaluationRun]] = defaultdict(list)
    for run in evaluations:
        if run.kind == "probe" and run.policy_version == 0:
            baselines[run.part].append(run)
    for part, runs in sorted(baselines.items()):
        solved = [run.solved for run in runs]
        print(
            f"- v0 third {part}: runs solved {solved} of {runs[0].problems}, "
            f"a spread of {100 * (max(solved) - min(solved)) / runs[0].problems:.1f} points"
        )
    starts = sorted(run.started for run in evaluations if run.kind == "probe" and run.started > loop_started_at)
    gaps = [(later - earlier) / 3600 for earlier, later in zip(starts, starts[1:], strict=False)]
    print(f"- probe slots beside the loop start every {statistics.median(gaps):.1f} h (median of {len(gaps)} gaps)")


def report_minif2f_searches(results: Path) -> None:
    lean = wall = verification = 0.0
    problems = 0
    for record in records(results):
        accounting = record["accounting"]
        lean += accounting["lean_seconds"]
        wall += accounting["wall_seconds"]
        verification += accounting["verification_seconds"]
        problems += 1
    print(
        f"- {results.parent.name} per search: Lean {lean / wall:.0%} of search wall time, final verification "
        f"{verification / wall:.0%} ({problems} searches; the rest waits on the policy and value servers)"
    )


def write_csv(path: Path, rows: Sequence[object]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([field.name for field in fields(rows[0])])
        writer.writerows(astuple(row) for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics", type=Path, default=Path("node_backup/2026-11-01/hf_run/run_logs/metrics"))
    parser.add_argument(
        "--evaluations", type=Path, default=Path("node_backup/2026-11-01/hf_dataset/evaluations/evaluations.jsonl")
    )
    parser.add_argument("--minif2f-runs", type=Path, default=Path("node_backup/2026-11-01/hf_run/evaluations"))
    parser.add_argument("--output", type=Path, default=Path("results/followup_step0"))
    arguments = parser.parse_args()

    status = read_status(arguments.metrics)
    samples = read_system(arguments.metrics)
    evaluations = read_evaluations(arguments.evaluations)
    ratings, passes = read_ratings(arguments.metrics)
    timeline = Timeline(status, evaluations)
    activities = [timeline.activity(sample.time) for sample in samples]
    totals = activity_totals(samples, activities, samples[-1].time)
    phases = build_phases(arguments.metrics, timeline, samples, activities, evaluations)
    versions = build_versions(ratings, evaluations, timeline, samples, activities, phases)

    report_activities(totals, samples[0].time, samples[-1].time)
    report_hardware(samples, activities)
    report_phases(phases)
    report_versions(versions, samples[0].time)
    report_passes(passes, samples, activities)
    report_costs(phases, evaluations, totals, timeline)
    report_probe_noise_and_cadence(evaluations, timeline.loop_started_at)
    for results in sorted(arguments.minif2f_runs.glob("*/results.jsonl")):
        report_minif2f_searches(results)

    arguments.output.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output / "phases.csv", phases)
    write_csv(
        arguments.output / "versions.csv",
        [
            VersionRow(
                policy_version=compute.rating.policy_version,
                rejected=compute.rating.rejected,
                published_at=datetime.fromtimestamp(compute.published_at, UTC).isoformat(timespec="minutes"),
                wall_hours=round(compute.totals.hours, 2),
                sampling_gpu_hours=round(GPUS * compute.totals.group_hours(Group.SAMPLING), 1),
                training_gpu_hours=round(GPUS * compute.totals.group_hours(Group.TRAINING), 1),
                other_gpu_hours=round(GPUS * compute.totals.group_hours(Group.OTHER), 1),
                lineage_gpu_hours=round(GPUS * compute.lineage_hours, 1),
                trees=compute.trees,
                expansions=compute.expansions,
                estimated_tokens=round(compute.estimated_tokens),
                probe_part=compute.part,
                probe_problems=compute.rating.problems,
                probe_solved=compute.rating.solved,
                points_at_16=round(
                    100 * (compute.rating.solved_within[-1] - compute.rating.baseline_solved_within[-1]), 1
                ),
                elo=round(ELO_PER_LOGIT * compute.rating.rating_logits),
                elo_lower=round(ELO_PER_LOGIT * compute.rating.lower_logits),
                elo_upper=round(ELO_PER_LOGIT * compute.rating.upper_logits),
            )
            for compute in versions
        ],
    )


@dataclass(frozen=True)
class VersionRow:
    policy_version: int
    rejected: bool
    published_at: str
    wall_hours: float
    sampling_gpu_hours: float
    training_gpu_hours: float
    other_gpu_hours: float
    lineage_gpu_hours: float
    trees: int
    expansions: int
    estimated_tokens: int
    probe_part: int
    probe_problems: int
    probe_solved: int
    points_at_16: float
    elo: int
    elo_lower: int
    elo_upper: int


if __name__ == "__main__":
    main()
