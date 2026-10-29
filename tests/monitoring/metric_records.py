import dataclasses

from lean_search.monitoring.families import (
    BandOutcome,
    CurriculumPhase,
    FailureTiers,
    GrpoPhase,
    LoopState,
    LoopStatus,
    PairedDifference,
    SearchPhase,
    SystemUsage,
    ValueArmResult,
)
from lean_search.rl.tree_statistics import BlockCounts, EdgeKindCounts, GraphStatistics, SizeHistogram
from lean_search.search.tactic_labels import TacticLabelCounts

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


def loop_status(
    last_publish_time: float | None = None, heartbeat_seconds: float = 60.0, server_failures: int = 0
) -> LoopStatus:
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
        server_failures=server_failures,
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


def system_usage(
    gpu_utilization: float = 90.0, memory_available_gib: float = 60.0, disk_free_gib: float = 400.0
) -> SystemUsage:
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
        memory_total_gib=120.0,
        memory_available_gib=memory_available_gib,
        disk_total_gib=500.0,
        disk_free_gib=disk_free_gib,
    )


def curriculum_phase(attempts: int = 100, solved: int = 50) -> CurriculumPhase:
    return CurriculumPhase(
        band_low=1.0,
        band_high=2.0,
        pool_statements=1000,
        verified_statements=500,
        by_difficulty={"1-2": BandOutcome(attempts, solved)},
    )


def value_arm(worse: bool) -> ValueArmResult:
    difference = PairedDifference(1, 56, 9 if worse else 4, 4, -0.09 if worse else 0.0, -0.2, 0.02, 0.02, 0.9)
    return ValueArmResult(
        slot=4,
        part=1,
        reference_value_version=0,
        published_value_version=4,
        reference_solved=30,
        published_solved=25 if worse else 30,
        this_slot=difference,
        same_value_version=difference,
        all_value_versions=difference,
        worse=worse,
    )
