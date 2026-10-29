import dataclasses

from lean_search.monitoring.families import (
    BandOutcome,
    CurriculumPhase,
    FailureTiers,
    GrpoPhase,
    LoopState,
    LoopStatus,
    SearchPhase,
    SystemUsage,
    ValueBenchmarkResult,
)
from lean_search.rl.tree_statistics import BlockCounts, EdgeKindCounts, GraphStatistics, SizeHistogram
from lean_search.search.tactic_labels import TacticLabelCounts
from lean_search.value.benchmark import (
    BenchmarkMetrics,
    CalibrationMetrics,
    EstimateKind,
    PairAccuracy,
    RankingMetrics,
    SeparationMetrics,
    StepMetrics,
)

ZERO_BY_TYPE = {
    int: 0,
    float: 0.0,
    EdgeKindCounts: EdgeKindCounts(),
    TacticLabelCounts: TacticLabelCounts(),
    SizeHistogram: SizeHistogram(),
    BlockCounts: BlockCounts(),
}


def graph_statistics(policy_samples: EdgeKindCounts) -> GraphStatistics:
    zeros = {field.name: ZERO_BY_TYPE[field.type] for field in dataclasses.fields(GraphStatistics)}
    return GraphStatistics(**{**zeros, "policy_samples": policy_samples})


def search_phase(
    new_state: int = 900, no_progress: int = 100, forced_answers: int = 0, repetition_loops: int = 0
) -> SearchPhase:
    return SearchPhase(
        graph=graph_statistics(EdgeKindCounts(new_state=new_state, no_progress=no_progress)),
        failure_tiers=FailureTiers(),
        expansions=100,
        lean_seconds=200.0,
        lean_seconds_per_expansion=2.0,
        forced_answers=forced_answers,
        repetition_loops=repetition_loops,
        mean_block_tactics=2.0,
    )


def loop_status(last_publish_time: float | None = None, heartbeat_seconds: float = 60.0) -> LoopStatus:
    return LoopStatus(
        state=LoopState.SEARCHING,
        heartbeat_seconds=heartbeat_seconds,
        searches_running=120,
        statements_attempted=100,
        statements_solved=50,
        proofs=300,
        proofs_per_hour=250.0,
        statements_per_hour=150.0,
        last_publish_time=last_publish_time,
    )


def grpo_phase(kl: float = 0.01, clip_fraction: float = 0.05, mixed_share: float = 0.4) -> GrpoPhase:
    return GrpoPhase(
        groups=900,
        group_samples=6300,
        mixed_reward_group_share=mixed_share,
        mean_local_reward=-0.2,
        mean_global_reward=0.6,
        kl_to_behaviour_policy=kl,
        clip_fraction=clip_fraction,
        mean_explanation_tokens=120.0,
        mean_block_tactics=2.0,
        policy_loss=0.0,
        trained_tokens=1_000_000,
        training_seconds=300.0,
    )


def system_usage(gpu_utilization: float = 90.0) -> SystemUsage:
    return SystemUsage(
        gpu_utilization=(gpu_utilization, gpu_utilization),
        gpu_memory_used_gib=(20.0, 20.0),
        gpu_memory_total_gib=(24.0, 24.0),
        gpu_power_watts=(300.0, 300.0),
        cpu_cores_used=60.0,
        cpu_cores_available=92.0,
        lean_cores_used=55.0,
        cpu_throttled_fraction=0.0,
        memory_used_gib=80.0,
        hourly_price=0.8,
        cost_so_far=10.0,
    )


def curriculum_phase(attempts: int = 100, solved: int = 50) -> CurriculumPhase:
    return CurriculumPhase(
        band_low=1.0,
        band_high=2.0,
        pool_statements=1000,
        verified_statements=500,
        by_difficulty={"1-2": BandOutcome(attempts, solved)},
    )


def value_result(gate_passed: bool) -> ValueBenchmarkResult:
    return ValueBenchmarkResult(
        candidate_version=1,
        gate_passed=gate_passed,
        benchmark=BenchmarkMetrics(
            estimates="fresh scores of value-v1",
            kind=EstimateKind.FRESH,
            model="value-v1",
            circular_runs=(),
            states=10,
            groups=4,
            states_without_estimate=0,
            ranking=RankingMetrics(
                4, 8, 0.7, PairAccuracy(2, 0.8), PairAccuracy(6, 0.6), PairAccuracy(5, 0.6), 0.5, 3, 1
            ),
            calibration=CalibrationMetrics(6, 0.1, 0.2, ()),
            separation=SeparationMetrics(0.7, 0.65),
            steps=StepMetrics(4, 1.2, 0.7),
        ),
    )
