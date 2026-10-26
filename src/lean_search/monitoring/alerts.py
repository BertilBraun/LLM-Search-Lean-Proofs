"""Warning rules over a run's metric families; thresholds come from the dashboard config."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.monitoring.store import FamilySeries, RunReader

POLICY_SAMPLES = "graph.policy_samples."


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Alert:
    severity: Severity
    title: str
    detail: str
    # The dashboard page that shows the metric.
    page: str


@dataclass(frozen=True)
class AlertThresholds:
    # Records averaged at the start and at the end of a series when judging a rise or a drop.
    window: int = 5
    stale_heartbeats: float = 5.0
    max_minutes_since_publish: float = 90.0
    max_no_progress_share: float = 0.35
    no_progress_rise: float = 0.05
    max_kl: float = 0.05
    max_clip_fraction: float = 0.2
    max_repetition_loop_share: float = 0.02
    repetition_loop_rise: float = 0.005
    min_math500_visible: float = 0.80
    max_math500_drop: float = 0.03
    min_mixed_group_share: float = 0.2
    min_gpu_utilization: float = 60.0
    min_solve_rate: float = 0.3
    max_solve_rate: float = 0.7
    failed_gates_in_a_row: int = 3


@dataclass(frozen=True)
class Trend:
    start: float | None
    recent: float


def present(values: Sequence[float | None]) -> list[float]:
    return [value for value in values if value is not None]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def trend(values: Sequence[float | None], window: int) -> Trend | None:
    known = present(values)
    if len(known) < 2 * window:
        return None
    return Trend(mean(known[:window]), mean(known[-window:]))


def ratios(series: FamilySeries, numerators: Sequence[str], denominator_prefix: str) -> list[float | None]:
    parts = [column for name, column in series.columns.items() if name.startswith(denominator_prefix)]
    counted = [series.columns[name] for name in numerators if name in series.columns]
    result: list[float | None] = []
    for index in range(len(series)):
        values = [column[index] for column in counted if column[index] is not None]
        total = sum(part[index] or 0.0 for part in parts)
        result.append(sum(values) / total if values and total > 0 else None)
    return result


def latest(values: Sequence[float | None]) -> float | None:
    known = present(values)
    return known[-1] if known else None


def loop_silence(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    status = reader.series("status")
    if not status.times:
        return Alert(Severity.INFO, "No status yet", "The loop has not written a status record.", "system")
    heartbeat = latest(status.columns.get("heartbeat_seconds", [])) or 60.0
    silent = now - status.times[-1]
    if silent <= thresholds.stale_heartbeats * heartbeat:
        return None
    return Alert(Severity.CRITICAL, "Loop silent", f"No status for {silent / 60:.0f} min.", "system")


def stale_publish(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    published = latest(reader.series("status").columns.get("last_publish_time", []))
    if published is None or now - published <= thresholds.max_minutes_since_publish * 60:
        return None
    minutes = (now - published) / 60
    return Alert(Severity.WARNING, "No publish", f"Last publish {minutes:.0f} min ago.", "policy")


def rising_share(values: Sequence[float | None], maximum: float, rise: float, window: int) -> Trend | None:
    """The trend when the recent share is above `maximum` or rose by more than `rise` (no start before 2 windows)."""
    current = trend(values, window)
    if current is not None and (current.recent > maximum or current.recent - (current.start or 0.0) > rise):
        return current
    recent = latest(values)
    if current is None and recent is not None and recent > maximum:
        return Trend(None, recent)
    return None


def share_text(found: Trend) -> str:
    return f"{found.recent:.1%}" + ("" if found.start is None else f" (start {found.start:.1%})")


def no_progress(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    # Back to the same state or to an ancestor: both are steps without progress.
    numerators = (f"{POLICY_SAMPLES}no_progress", f"{POLICY_SAMPLES}back_to_ancestor")
    shares = ratios(reader.series("search"), numerators, POLICY_SAMPLES)
    found = rising_share(shares, thresholds.max_no_progress_share, thresholds.no_progress_rise, thresholds.window)
    if found is None:
        return None
    detail = f"No-progress share of policy samples {share_text(found)}: possible reward hacking."
    return Alert(Severity.WARNING, "No-progress rising", detail, "search")


def repetition_loops(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    shares = ratios(reader.series("search"), ("repetition_loops",), POLICY_SAMPLES)
    found = rising_share(
        shares, thresholds.max_repetition_loop_share, thresholds.repetition_loop_rise, thresholds.window
    )
    if found is None:
        return None
    return Alert(Severity.WARNING, "Repetition loops", f"Share of policy samples {share_text(found)}.", "search")


def latest_above(reader: RunReader, family: str, name: str, label: str, maximum: float, page: str) -> Alert | None:
    value = latest(reader.series(family).columns.get(name, []))
    if value is None or value <= maximum:
        return None
    return Alert(Severity.WARNING, f"{label} high", f"{label} {value:.3g} > {maximum:.3g}.", page)


def high_kl(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    return latest_above(reader, "grpo", "kl_to_behaviour_policy", "KL", thresholds.max_kl, "policy")


def high_clip_fraction(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    return latest_above(reader, "grpo", "clip_fraction", "Clip fraction", thresholds.max_clip_fraction, "policy")


def math_retention(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    measured = present(reader.series("fixed_targets").columns.get("math500_visible", []))
    if not measured:
        return None
    baseline, current = measured[0], measured[-1]
    if current < thresholds.min_math500_visible:
        detail = f"MATH-500 visible {current:.1%} < {thresholds.min_math500_visible:.0%}."
        return Alert(Severity.CRITICAL, "MATH-500 dropping", detail, "evaluations")
    if baseline - current > thresholds.max_math500_drop:
        detail = f"MATH-500 visible {current:.1%}, baseline {baseline:.1%}."
        return Alert(Severity.WARNING, "MATH-500 dropping", detail, "evaluations")
    return None


def few_mixed_groups(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    share = latest(reader.series("grpo").columns.get("mixed_reward_group_share", []))
    if share is None or share >= thresholds.min_mixed_group_share:
        return None
    detail = f"Only {share:.0%} of groups have mixed rewards: little signal."
    return Alert(Severity.WARNING, "Few mixed groups", detail, "policy")


def idle_gpus(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    system = reader.series("system")
    gpus = [column for name, column in system.columns.items() if name.startswith("gpu_utilization.")]
    recent = [value for column in gpus for value in present(column[-thresholds.window :])]
    if not recent or mean(recent) >= thresholds.min_gpu_utilization:
        return None
    return Alert(Severity.INFO, "GPUs underused", f"Mean GPU utilization {mean(recent):.0f}%.", "system")


def solve_rate_off_target(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    curriculum = reader.series("curriculum")
    if not curriculum.times:
        return None
    attempts = sum(
        column[-1] or 0.0
        for name, column in curriculum.columns.items()
        if name.startswith("by_difficulty.") and name.endswith(".attempts")
    )
    solved = sum(
        column[-1] or 0.0
        for name, column in curriculum.columns.items()
        if name.startswith("by_difficulty.") and name.endswith(".solved")
    )
    if attempts == 0 or thresholds.min_solve_rate <= solved / attempts <= thresholds.max_solve_rate:
        return None
    detail = (
        f"Solve rate {solved / attempts:.0%}, target {thresholds.min_solve_rate:.0%}–{thresholds.max_solve_rate:.0%}."
    )
    return Alert(Severity.INFO, "Curriculum off target", detail, "curriculum")


def failing_gates(reader: RunReader, thresholds: AlertThresholds, now: float) -> Alert | None:
    passed = present(reader.series("value").columns.get("gate_passed", []))
    count = thresholds.failed_gates_in_a_row
    if len(passed) < count or any(passed[-count:]):
        return None
    detail = f"The last {count} value candidates failed the gate."
    return Alert(Severity.INFO, "Value gate failing", detail, "value")


RULES = (
    loop_silence,
    stale_publish,
    no_progress,
    repetition_loops,
    high_kl,
    high_clip_fraction,
    math_retention,
    few_mixed_groups,
    idle_gpus,
    solve_rate_off_target,
    failing_gates,
)

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


def run_alerts(reader: RunReader, thresholds: AlertThresholds, now: float) -> list[Alert]:
    alerts = [alert for rule in RULES if (alert := rule(reader, thresholds, now)) is not None]
    return sorted(alerts, key=lambda alert: SEVERITY_ORDER[alert.severity])
