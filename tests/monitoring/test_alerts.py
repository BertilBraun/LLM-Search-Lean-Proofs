from collections.abc import Callable
from pathlib import Path

import pytest
from metric_records import curriculum_phase, grpo_phase, loop_status, search_phase, system_usage, value_arm

from lean_search.monitoring.alerts import AlertThresholds, Severity, run_alerts
from lean_search.monitoring.families import (
    FixedTargets,
    HealthAlert,
    HealthCheck,
    HealthMeasurements,
    HealthSeverity,
    HealthThresholds,
    PhaseHealth,
)
from lean_search.monitoring.store import MetricsWriter, RunReader

NOW = 100_000.0
THRESHOLDS = AlertThresholds(window=2)


def alert_titles(run_directory: Path) -> set[str]:
    return {alert.title for alert in run_alerts(RunReader(run_directory), THRESHOLDS, NOW)}


def with_status(writer: MetricsWriter) -> None:
    writer.write(loop_status(last_publish_time=NOW - 60), record_time=NOW - 30)


def write_all(writer: MetricsWriter, records: list[object]) -> None:
    for index, record in enumerate(records):
        writer.write(record, record_time=NOW - 1000 + index)


def silent_loop(writer: MetricsWriter) -> None:
    writer.write(loop_status(last_publish_time=NOW - 60, heartbeat_seconds=60), record_time=NOW - 3600)


def missed_publish(writer: MetricsWriter) -> None:
    writer.write(loop_status(last_publish_time=NOW - 4 * 3600), record_time=NOW - 30)


def rising_no_progress(writer: MetricsWriter) -> None:
    write_all(writer, [search_phase(no_progress=100), search_phase(no_progress=100)])
    write_all(writer, [search_phase(new_state=800, no_progress=200), search_phase(new_state=800, no_progress=200)])


def high_no_progress(writer: MetricsWriter) -> None:
    writer.write(search_phase(new_state=500, no_progress=500), record_time=NOW)


def repetition_loops(writer: MetricsWriter) -> None:
    writer.write(search_phase(forced_answers=50, repetition_loops=40), record_time=NOW)


def high_kl(writer: MetricsWriter) -> None:
    writer.write(grpo_phase(kl=0.2), record_time=NOW)


def phase_health(*alerts: HealthAlert) -> PhaseHealth:
    return PhaseHealth(1, 1, HealthMeasurements(), HealthThresholds(0.02, 0.1), alerts)


def clip_alert() -> HealthAlert:
    return HealthAlert(HealthCheck.CLIP_FRACTION, HealthSeverity.WARNING, "Clip fraction high", "0.3 > 0.1")


def loop_health_alert(writer: MetricsWriter) -> None:
    writer.write(phase_health(clip_alert()), record_time=NOW)


def math_below_minimum(writer: MetricsWriter) -> None:
    writer.write(FixedTargets(math500_visible=0.70), record_time=NOW)


def math_drop(writer: MetricsWriter) -> None:
    write_all(writer, [FixedTargets(math500_visible=0.88), FixedTargets(math500_visible=0.83)])


def few_mixed_groups(writer: MetricsWriter) -> None:
    writer.write(grpo_phase(mixed_share=0.05), record_time=NOW)


def idle_gpus(writer: MetricsWriter) -> None:
    writer.write(system_usage(gpu_utilization=20.0), record_time=NOW)


def solve_rate_too_high(writer: MetricsWriter) -> None:
    writer.write(curriculum_phase(attempts=100, solved=95), record_time=NOW)


def worse_value_arm(writer: MetricsWriter) -> None:
    writer.write(value_arm(worse=True), record_time=NOW)


def low_host_memory(writer: MetricsWriter) -> None:
    writer.write(system_usage(memory_available_gib=6.0), record_time=NOW)


def low_disk(writer: MetricsWriter) -> None:
    writer.write(system_usage(disk_free_gib=20.0), record_time=NOW)


def failing_servers(writer: MetricsWriter) -> None:
    writer.write(loop_status(last_publish_time=NOW - 60, server_failures=12), record_time=NOW - 30)


@pytest.mark.parametrize(
    ("scenario", "title"),
    [
        (silent_loop, "Loop silent"),
        (missed_publish, "No publish"),
        (rising_no_progress, "No-progress rising"),
        (high_no_progress, "No-progress rising"),
        (repetition_loops, "Repetition loops"),
        (high_kl, "KL high"),
        (loop_health_alert, "Clip fraction high"),
        (math_below_minimum, "MATH-500 dropping"),
        (math_drop, "MATH-500 dropping"),
        (few_mixed_groups, "Few mixed groups"),
        (idle_gpus, "GPUs underused"),
        (solve_rate_too_high, "Curriculum off target"),
        (worse_value_arm, "Value model worse than v0"),
        (low_host_memory, "Host memory low"),
        (low_disk, "Disk almost full"),
        (failing_servers, "Server failures"),
    ],
)
def test_rule_fires(tmp_path: Path, scenario: Callable[[MetricsWriter], None], title: str) -> None:
    writer = MetricsWriter(tmp_path)
    scenario(writer)
    assert title in alert_titles(tmp_path)


def steady_search(writer: MetricsWriter) -> None:
    write_all(writer, [search_phase()] * 4)


def calm_grpo(writer: MetricsWriter) -> None:
    writer.write(grpo_phase(), record_time=NOW)


def retained_math(writer: MetricsWriter) -> None:
    write_all(writer, [FixedTargets(math500_visible=0.88), FixedTargets(math500_visible=0.87)])


def busy_gpus(writer: MetricsWriter) -> None:
    writer.write(system_usage(gpu_utilization=95.0), record_time=NOW)


def balanced_curriculum(writer: MetricsWriter) -> None:
    writer.write(curriculum_phase(attempts=100, solved=50), record_time=NOW)


def value_arm_no_worse(writer: MetricsWriter) -> None:
    write_all(writer, [value_arm(worse=True), value_arm(worse=False)])


def healthy_phase_after_an_alert(writer: MetricsWriter) -> None:
    write_all(writer, [phase_health(clip_alert()), phase_health()])


@pytest.mark.parametrize(
    "scenario",
    [
        steady_search,
        calm_grpo,
        retained_math,
        busy_gpus,
        balanced_curriculum,
        value_arm_no_worse,
        healthy_phase_after_an_alert,
    ],
)
def test_healthy_run_has_no_alerts(tmp_path: Path, scenario: Callable[[MetricsWriter], None]) -> None:
    writer = MetricsWriter(tmp_path)
    with_status(writer)
    scenario(writer)
    assert alert_titles(tmp_path) == set()


def test_missing_status_is_reported(tmp_path: Path) -> None:
    MetricsWriter(tmp_path)
    assert alert_titles(tmp_path) == {"No status yet"}


def test_the_loops_hard_stop_is_critical(tmp_path: Path) -> None:
    stop = HealthAlert(HealthCheck.HELD_OUT_VALID_LEAN, HealthSeverity.STOP, "Held-out valid Lean collapsed", "")
    MetricsWriter(tmp_path).write(phase_health(stop), record_time=NOW)
    alerts = run_alerts(RunReader(tmp_path), THRESHOLDS, NOW)
    assert [alert.severity for alert in alerts if alert.page == "training"] == [Severity.CRITICAL]


def test_critical_alerts_come_first(tmp_path: Path) -> None:
    writer = MetricsWriter(tmp_path)
    writer.write(grpo_phase(kl=0.2), record_time=NOW)
    silent_loop(writer)
    assert run_alerts(RunReader(tmp_path), THRESHOLDS, NOW)[0].severity == Severity.CRITICAL
