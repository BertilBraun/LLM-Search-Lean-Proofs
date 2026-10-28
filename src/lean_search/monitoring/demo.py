"""Synthetic metrics of a multi-day RL run (and its outcome-only control), written through `MetricsWriter`, so the
dashboard can be viewed and tested before the loop exists. The numbers start at the measured baselines of the
visible student v2 and drift the way a working loop might."""

import dataclasses
import math
import random
import time
from dataclasses import dataclass

from lean_search.monitoring.families import (
    BandOutcome,
    CurriculumPhase,
    FailureTiers,
    FixedTargets,
    GrpoPhase,
    LoopState,
    LoopStatus,
    SearchPhase,
    SystemUsage,
    ValueBenchmarkResult,
)
from lean_search.monitoring.store import LoopContext, MetricsWriter
from lean_search.rl.tree_statistics import EdgeKindCounts, GraphStatistics, SizeHistogram
from lean_search.value.benchmark import (
    BenchmarkMetrics,
    CalibrationMetrics,
    EstimateKind,
    PairAccuracy,
    RankingMetrics,
    ReliabilityBin,
    SeparationMetrics,
    StepMetrics,
)

GPUS = 4
CORES = 92.0
HOURLY_PRICE = 0.80
MINIF2F_VALID = 244
DIFFICULTY_BANDS = ("0-1", "1-2", "2-3", "3-4", "4-5", "5+")


@dataclass(frozen=True)
class DemoSchedule:
    phase_minutes: float = 25.0
    training_minutes: float = 5.0
    status_seconds: float = 120.0
    system_seconds: float = 60.0
    evaluation_every_phases: int = 6
    value_every_phases: int = 4


@dataclass(frozen=True)
class DemoProfile:
    # The outcome-only control learns more slowly and earns no local reward.
    control: bool
    minif2f_gain: float
    held_out_gain: float
    math500_drift: float


MAIN_PROFILE = DemoProfile(control=False, minif2f_gain=16.0, held_out_gain=0.05, math500_drift=-0.035)
CONTROL_PROFILE = DemoProfile(control=True, minif2f_gain=7.0, held_out_gain=0.02, math500_drift=-0.01)


def counts(total: int, shares: dict[str, float]) -> EdgeKindCounts:
    scale = total / sum(shares.values())
    return EdgeKindCounts(**{kind: round(share * scale) for kind, share in shares.items()})


def scaled(values: EdgeKindCounts, factor: float) -> EdgeKindCounts:
    return EdgeKindCounts(*(round(count * factor) for count in dataclasses.astuple(values)))


def histogram(random_source: random.Random, count: int, mean_size: float) -> SizeHistogram:
    sizes = [max(1, round(random_source.expovariate(1 / mean_size))) for _ in range(count)]
    return SizeHistogram.of(sizes)


class DemoRun:
    def __init__(
        self, writer: MetricsWriter, profile: DemoProfile, schedule: DemoSchedule, started_at: float, seed: int
    ) -> None:
        self.writer = writer
        self.profile = profile
        self.schedule = schedule
        self.started_at = started_at
        self.random = random.Random(seed)
        self.phase = 0
        self.value_version = 0
        self.next_status = started_at
        self.next_system = started_at
        self.next_phase_end = started_at + schedule.phase_minutes * 60
        self.last_publish: float | None = None
        self.proofs = 0
        self.statements_attempted = 0
        self.statements_solved = 0
        self.band_low = 1.0
        self.context()
        self.write_fixed_targets(started_at)

    def progress(self, moment: float) -> float:
        hours = (moment - self.started_at) / 3600
        return 1 - math.exp(-hours / 30)

    def noise(self, scale: float) -> float:
        return self.random.gauss(0.0, scale)

    def context(self) -> None:
        self.writer.context = LoopContext(self.phase, self.phase, self.value_version)

    def state(self, moment: float) -> LoopState:
        phase_start = self.next_phase_end - self.schedule.phase_minutes * 60
        if moment - phase_start < self.schedule.training_minutes * 60 and self.phase > 0:
            return LoopState.TRAINING
        return LoopState.SEARCHING

    def advance(self, until: float) -> None:
        """Writes every record due up to `until`, in time order."""
        while True:
            moment = min(self.next_status, self.next_system, self.next_phase_end)
            if moment > until:
                return
            self.context()
            if moment == self.next_phase_end:
                self.finish_phase(moment)
                self.next_phase_end += self.schedule.phase_minutes * 60 * (1 + self.noise(0.08))
            elif moment == self.next_system:
                self.write_system(moment)
                self.next_system += self.schedule.system_seconds
            else:
                self.write_status(moment)
                self.next_status += self.schedule.status_seconds

    def write_status(self, moment: float) -> None:
        state = self.state(moment)
        hours = self.schedule.status_seconds / 3600
        rate = 0.0 if state == LoopState.TRAINING else 260 * (1 + 0.3 * self.progress(moment)) + self.noise(15)
        statements = 0.0 if state == LoopState.TRAINING else 150 + self.noise(10)
        self.proofs += round(rate * hours)
        attempted = round(statements * hours)
        self.statements_attempted += attempted
        self.statements_solved += round(attempted * (0.48 + self.noise(0.04)))
        self.writer.write(
            LoopStatus(
                state=state,
                heartbeat_seconds=self.schedule.status_seconds,
                searches_running=0 if state == LoopState.TRAINING else 120,
                statements_attempted=self.statements_attempted,
                statements_solved=self.statements_solved,
                proofs=self.proofs,
                proofs_per_hour=max(0.0, rate),
                statements_per_hour=max(0.0, statements),
                last_publish_time=self.last_publish,
            ),
            record_time=moment,
        )

    def write_system(self, moment: float) -> None:
        training = self.state(moment) == LoopState.TRAINING
        utilization = tuple(
            min(100.0, max(0.0, (98 if index < 2 else 8) + self.noise(2)))
            if training
            else min(100.0, max(0.0, 91 + self.noise(4)))
            for index in range(GPUS)
        )
        lean = 4.0 + self.noise(1) if training else 71 + self.noise(5)
        self.writer.write(
            SystemUsage(
                gpu_utilization=utilization,
                gpu_memory_used_gib=tuple(21.5 + self.noise(0.3) for _ in range(GPUS)),
                gpu_memory_total_gib=(24.0,) * GPUS,
                gpu_power_watts=tuple(3.3 * value + 40 for value in utilization),
                cpu_cores_used=lean + 6 + self.noise(0.5),
                cpu_cores_available=CORES,
                lean_cores_used=max(0.0, lean),
                cpu_throttled_fraction=max(0.0, self.noise(0.01)),
                memory_used_gib=88 + self.noise(3),
                hourly_price=HOURLY_PRICE,
                cost_so_far=HOURLY_PRICE * (moment - self.started_at) / 3600,
            ),
            record_time=moment,
        )

    def finish_phase(self, moment: float) -> None:
        self.write_search(moment)
        self.write_curriculum(moment)
        self.write_grpo(moment + 240)
        self.phase += 1
        self.last_publish = moment + 270
        self.context()
        if self.phase % self.schedule.value_every_phases == 0:
            self.write_value(moment + 280)
        if self.phase % self.schedule.evaluation_every_phases == 0:
            self.write_fixed_targets(moment + 290)

    def write_fixed_targets(self, moment: float) -> None:
        learned = self.progress(moment)
        self.writer.write(
            FixedTargets(
                minif2f_valid_solved=round(166 + self.profile.minif2f_gain * learned + self.noise(2.5)),
                minif2f_valid_problems=MINIF2F_VALID,
                expansion_budget=32,
                held_out_success=0.421 + self.profile.held_out_gain * learned + self.noise(0.004),
                held_out_states=512,
                math500_visible=0.876 + self.profile.math500_drift * learned + self.noise(0.006),
                math500_thinking=0.845 + self.profile.math500_drift * learned * 0.5 + self.noise(0.006),
            ),
            record_time=moment,
        )

    def write_grpo(self, moment: float) -> None:
        learned = self.progress(moment)
        groups = round(900 + self.noise(60))
        spike = 0.03 if self.random.random() < 0.04 else 0.0
        self.writer.write(
            GrpoPhase(
                groups=groups,
                group_samples=groups * 7,
                mixed_reward_group_share=0.46 - 0.08 * learned + self.noise(0.02),
                mean_local_reward=0.0 if self.profile.control else -0.32 + 0.18 * learned + self.noise(0.02),
                mean_global_reward=0.55 + 0.25 * learned + self.noise(0.03),
                off_proof_graph_local_reward_share=0.0
                if self.profile.control
                else 0.36 - 0.06 * learned + self.noise(0.015),
                kl_to_behaviour_policy=max(0.0, 0.015 + 0.01 * learned + abs(self.noise(0.004)) + spike),
                clip_fraction=max(0.0, 0.06 + 0.04 * learned + self.noise(0.01)),
                mean_explanation_tokens=121 - 14 * learned + self.noise(3),
                mean_block_tactics=2.1 + 0.5 * learned + self.noise(0.05),
                policy_loss=-0.02 + self.noise(0.01),
                trained_tokens=round(groups * 7 * 180),
                training_seconds=self.schedule.training_minutes * 60 * (1 + self.noise(0.05)),
            ),
            record_time=moment,
        )

    def write_search(self, moment: float) -> None:
        learned = self.progress(moment)
        trees = round(62 + self.noise(5))
        solved = round(trees * (0.5 + self.noise(0.04)))
        samples = round(trees * 48 * 8)
        no_progress = 0.075 + 0.09 * learned * (0.3 if self.profile.control else 1.0)
        policy_samples = counts(
            samples,
            {
                "lean_error": 0.47 - 0.06 * learned,
                "heartbeat_timeout": 0.024,
                "wall_clock_timeout": 0.002,
                "infrastructure_failure": 0.001,
                "new_state": 0.24 + 0.03 * learned,
                "no_progress": no_progress + self.noise(0.004),
                "back_to_ancestor": 0.012,
                "sibling_state": 0.07,
                "transposition": 0.045,
                "repeat": 0.035,
            },
        )
        policy_edges = scaled(policy_samples, 0.6)
        automation_edges = counts(
            round(samples * 0.35), {"lean_error": 0.708, "new_state": 0.12, "no_progress": 0.15, "transposition": 0.02}
        )
        edges = EdgeKindCounts(
            **{
                name: getattr(policy_edges, name) + getattr(automation_edges, name)
                for name in EdgeKindCounts.__dataclass_fields__
            }
        )
        nodes = edges.new_state + trees
        expanded = round(trees * 48)
        groups = round(expanded * 0.95)
        graph = GraphStatistics(
            trees=trees,
            solved_trees=solved,
            nodes=nodes,
            expanded_nodes=expanded,
            never_expanded_nodes=nodes - expanded,
            edges=edges,
            policy_edges=policy_edges,
            automation_edges=automation_edges,
            policy_samples=policy_samples,
            partial_failures=round(samples * 0.04),
            repeats_of_failed_automation=round(samples * (0.034 - 0.01 * learned)),
            forced_edges=round(samples * 0.004),
            proof_path_nodes=solved * 6,
            proof_graph_nodes=solved * 6 + round(solved * 0.2),
            off_path_proof_graph_nodes=round(solved * 0.2),
            transpositions_into_proof_graph=round(solved * 1.3),
            off_path_transpositions_into_proof_graph=round(solved * 0.25),
            off_path_transposition_sources=round(solved * 0.2),
            off_path_transpositions_into_proof_path=round(solved * 0.22),
            dead_ends=round(expanded * (0.28 - 0.04 * learned)),
            expanded_off_graph_nodes=round(expanded * 0.55),
            proof_graph_targets=solved * 6,
            off_graph_targets=round(expanded * 0.66),
            targets_averaging_descendants=round(expanded * 0.4),
            targets_without_value_part=0,
            expanded_without_target=round(expanded * 0.15),
            off_graph_subtree_sizes=histogram(self.random, round(expanded * 0.66), 3.0),
            expanded_subtree_sizes=histogram(self.random, expanded, 4.0),
            groups=groups,
            group_samples=groups * 7,
            groups_with_mixed_rewards=round(groups * (0.46 - 0.08 * learned)),
            outcome_groups_with_mixed_rewards=round(groups * 0.12),
            local_reward=samples * (-0.3 + 0.15 * learned),
            global_reward=samples * (0.5 + 0.2 * learned),
            positive_local_reward=samples * 0.08,
            positive_local_reward_off_proof_graph=samples * 0.08 * (0.36 - 0.06 * learned),
        )
        policy_total = policy_samples.total
        forced = round(policy_total * 0.004)
        self.writer.write(
            SearchPhase(
                graph=graph,
                failure_tiers=FailureTiers(
                    malformed=round(policy_total * (0.05 - 0.01 * learned)),
                    invalid_in_state=round(policy_total * (0.088 - 0.02 * learned)),
                    valid_but_failing=round(policy_total * (0.337 - 0.03 * learned)),
                    timeout=round(policy_total * 0.026),
                ),
                expansions=expanded,
                lean_seconds=expanded * (2.4 - 0.4 * learned),
                lean_seconds_per_expansion=2.4 - 0.4 * learned + self.noise(0.1),
                forced_answers=forced,
                repetition_loops=round(forced * (0.6 + 0.2 * learned)),
                mean_block_tactics=2.1 + 0.5 * learned + self.noise(0.05),
            ),
            record_time=moment,
        )

    def write_curriculum(self, moment: float) -> None:
        self.band_low = min(4.5, self.band_low + max(-0.5, self.noise(0.12) + 0.03))
        by_difficulty = {}
        for index, band in enumerate(DIFFICULTY_BANDS):
            distance = index + 0.5 - (self.band_low + 0.5)
            attempts = max(0, round(80 * math.exp(-(distance**2)) + self.noise(3)))
            rate = min(1.0, max(0.0, 0.55 - 0.18 * distance + self.noise(0.04)))
            by_difficulty[band] = BandOutcome(attempts, round(attempts * rate))
        stages = {
            f"stage {stage}": BandOutcome(round(150 / (stage + 1)), round(70 / (stage + 1.5))) for stage in range(3)
        }
        self.writer.write(
            CurriculumPhase(
                band_low=self.band_low,
                band_high=self.band_low + 1.0,
                pool_statements=41200,
                verified_statements=min(41200, 6000 + round(self.phase * 160)),
                by_difficulty=by_difficulty,
                by_stage=stages,
            ),
            record_time=moment,
        )

    def write_value(self, moment: float) -> None:
        learned = self.progress(moment)
        passed = self.random.random() < 0.5
        if passed:
            self.value_version += 1
        bins = tuple(
            ReliabilityBin(
                lower=index / 10,
                upper=(index + 1) / 10,
                states=round(300 * math.exp(-((index - 5) ** 2) / 8)),
                mean_predicted=(index + 0.5) / 10,
                mean_target=min(1.0, max(0.0, (index + 0.5) / 10 + (0.12 - 0.08 * learned) * (0.5 - index / 10))),
            )
            for index in range(10)
        )
        benchmark = BenchmarkMetrics(
            estimates=f"fresh scores of value-v{self.value_version + 1}",
            kind=EstimateKind.FRESH,
            model=f"value-v{self.value_version + 1}",
            circular_runs=(),
            states=3800,
            groups=1450,
            states_without_estimate=0,
            ranking=RankingMetrics(
                groups_with_proof_state=640,
                pairs=900,
                pairwise_accuracy=0.63 + 0.11 * learned + self.noise(0.01),
                proof_over_dead_end=PairAccuracy(60, 0.68 + 0.12 * learned + self.noise(0.01)),
                proof_over_expanded=PairAccuracy(840, 0.58 + 0.08 * learned + self.noise(0.01)),
                expanded_over_dead_end=PairAccuracy(2400, 0.61 + 0.06 * learned + self.noise(0.01)),
                top_accuracy=0.41 + 0.12 * learned + self.noise(0.015),
                never_expanded_siblings=1900,
                unexplored_expanded_siblings=120,
            ),
            calibration=CalibrationMetrics(
                anchor_states=2100,
                anchor_expected_calibration_error=0.17 - 0.09 * learned + abs(self.noise(0.01)),
                anchor_brier_score=0.23 - 0.07 * learned + abs(self.noise(0.01)),
                anchor_bins=bins,
            ),
            separation=SeparationMetrics(
                proof_graph_over_dead_end_auc=0.56 + 0.2 * learned + self.noise(0.015),
                expanded_over_dead_end_auc=0.52 + 0.15 * learned + self.noise(0.015),
            ),
            steps=StepMetrics(
                proof_graph_states=1200,
                mean_absolute_error=1.55 - 0.4 * learned + self.noise(0.04),
                spearman=0.62 + 0.12 * learned + self.noise(0.015),
            ),
        )
        candidate = round(150 + 6 * learned + self.noise(3))
        self.writer.write(
            ValueBenchmarkResult(
                candidate_version=self.value_version if passed else self.value_version + 1,
                gate_passed=passed,
                benchmark=benchmark,
                ab_problems=MINIF2F_VALID,
                ab_solved_candidate=candidate,
                ab_solved_current=candidate - round(abs(self.noise(3))) * (1 if passed else -1),
                training_loss=0.9 - 0.2 * learned + self.noise(0.02),
            ),
            record_time=moment,
        )


def demo_runs(
    main: MetricsWriter, control: MetricsWriter, days: float, schedule: DemoSchedule, now: float
) -> tuple[DemoRun, DemoRun]:
    started_at = now - days * 86400
    runs = (
        DemoRun(main, MAIN_PROFILE, schedule, started_at, seed=1),
        DemoRun(control, CONTROL_PROFILE, schedule, started_at, seed=2),
    )
    for run in runs:
        run.advance(now)
    return runs


def keep_live(runs: tuple[DemoRun, ...], interval_seconds: float) -> None:
    while True:
        time.sleep(interval_seconds)
        for run in runs:
            run.advance(time.time())
