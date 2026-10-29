"""Per-phase health checks of the GRPO loop: training stability, the policy's outputs, the held-out states and the
search budget, each against a threshold; alerts go to loop.log and the dashboard (the `health` family).

Absolute limits: the KL to the starting policy (version 0's is 0) and the clip fraction. Relative limits: distinct
samples per expansion, explanation length and cut-off samples against the mean of the first `reference_phases` phases;
the held-out valid-Lean rate and per-sample success against version 0's held-out evaluation. One check stops the loop:
a held-out valid-Lean rate below `stop_held_out_valid_fraction` of version 0's. The loop then closes the phase, writes
`health_stop.json` and refuses to start until the owner rolls back to the last good version (`publish_rollback`) or
clears the stop. Every default is a first guess, to be calibrated on the first phases.
"""

import dataclasses
import datetime
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, Publisher, read_versions, record_published
from lean_search.monitoring.families import (
    BudgetPhase,
    HealthAlert,
    HealthCheck,
    HealthMeasurements,
    HealthSeverity,
    HealthThresholds,
    PhaseHealth,
)
from lean_search.rl.evaluation import EvaluationSummary
from lean_search.rl.loop_config import HealthConfig
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.rl.tree_store import TreeEntry
from lean_search.search.records import from_json_object, to_json


@dataclass(frozen=True)
class HeldOutRates:
    valid_rate: float
    success: float


@dataclass(frozen=True)
class HealthStop:
    """Written when the hard stop triggers; the loop refuses to start while it exists."""

    phase: int
    policy_version: int
    last_good_version: int
    reason: str
    stopped_at: str


def held_out_rates(summary: EvaluationSummary) -> HeldOutRates | None:
    if not summary.samples:
        return None
    return HeldOutRates(summary.valid_samples / summary.samples, summary.solved / summary.samples)


def share(part: int, total: int) -> float | None:
    return part / total if total else None


def measurements(
    outcome: PhaseOutcome | None, entries: Sequence[TreeEntry], held_out: HeldOutRates | None
) -> HealthMeasurements:
    """`entries`: the phase's trees; `held_out`: the held-out evaluation after the phase, if one ran."""
    summaries = [entry.summary for entry in entries]
    expansions = sum(summary.policy_expansions for summary in summaries)
    samples = sum(summary.policy_samples for summary in summaries)
    policy = None if outcome is None else outcome.policy
    trained = policy is not None and policy.data.sequences > 0
    return HealthMeasurements(
        kl_to_starting_policy=policy.result.final_kl_to_reference if trained else None,
        clip_fraction=policy.result.final_clip_fraction if trained else None,
        distinct_samples_per_expansion=share(sum(summary.distinct_blocks for summary in summaries), expansions),
        distinct_texts_per_expansion=share(sum(summary.distinct_texts for summary in summaries), expansions),
        mean_explanation_tokens=policy.data.mean_explanation_tokens if trained else None,
        cut_off_share=share(sum(summary.cut_off_samples for summary in summaries), samples),
        repetition_loop_share=share(sum(summary.repetition_loops for summary in summaries), samples),
        held_out_valid_rate=None if held_out is None else held_out.valid_rate,
        held_out_success=None if held_out is None else held_out.success,
    )


def reference_measurements(history: Sequence[PhaseHealth], phases: int) -> HealthMeasurements | None:
    """Each signal's mean over the first `phases` phases; None until they are all recorded."""
    first = [record.measured for record in history if record.phase <= phases]
    if len(first) < phases:
        return None
    means = {}
    for item in dataclasses.fields(HealthMeasurements):
        values = [value for record in first if (value := getattr(record, item.name)) is not None]
        means[item.name] = statistics.fmean(values) if values else None
    return HealthMeasurements(**means)


def scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def health_thresholds(
    config: HealthConfig, reference: HealthMeasurements | None, version_zero: HeldOutRates | None
) -> HealthThresholds:
    thresholds = HealthThresholds(config.max_kl_to_starting_policy, config.max_clip_fraction)
    if reference is not None:
        cut_off = reference.cut_off_share
        thresholds = dataclasses.replace(
            thresholds,
            min_distinct_samples_per_expansion=scaled(
                reference.distinct_samples_per_expansion, config.min_distinct_samples_fraction
            ),
            min_explanation_tokens=scaled(reference.mean_explanation_tokens, config.min_explanation_fraction),
            max_explanation_tokens=scaled(reference.mean_explanation_tokens, config.max_explanation_fraction),
            max_cut_off_share=None
            if cut_off is None
            else max(cut_off * config.max_cut_off_factor, cut_off + config.min_cut_off_rise),
        )
    if version_zero is not None:
        thresholds = dataclasses.replace(
            thresholds,
            min_held_out_valid_rate=version_zero.valid_rate * config.min_held_out_valid_fraction,
            stop_held_out_valid_rate=version_zero.valid_rate * config.stop_held_out_valid_fraction,
            min_held_out_success=version_zero.success * config.min_held_out_success_fraction,
        )
    return thresholds


def above(value: float | None, limit: float | None) -> bool:
    return value is not None and limit is not None and value > limit


def below(value: float | None, limit: float | None) -> bool:
    return value is not None and limit is not None and value < limit


def alert_title(check: HealthCheck, severity: HealthSeverity) -> str:
    match check:
        case HealthCheck.KL_TO_STARTING_POLICY:
            return "KL to the starting policy high"
        case HealthCheck.CLIP_FRACTION:
            return "Clip fraction high"
        case HealthCheck.DISTINCT_SAMPLES:
            return "Samples collapsing"
        case HealthCheck.EXPLANATION_LENGTH:
            return "Explanation length drifting"
        case HealthCheck.CUT_OFF_SAMPLES:
            return "Samples cut off at the token cap"
        case HealthCheck.HELD_OUT_VALID_LEAN if severity == HealthSeverity.STOP:
            return "Held-out valid Lean collapsed: loop stopped"
        case HealthCheck.HELD_OUT_VALID_LEAN:
            return "Held-out valid Lean dropping"
        case HealthCheck.HELD_OUT_SUCCESS:
            return "Held-out success dropping"
        case HealthCheck.SEARCH_BUDGET:
            return "Search budget may be too small"


def health_alert(check: HealthCheck, severity: HealthSeverity, detail: str) -> HealthAlert:
    return HealthAlert(check, severity, alert_title(check, severity), detail)


def health_alerts(
    measured: HealthMeasurements, thresholds: HealthThresholds, budget: BudgetPhase, config: HealthConfig
) -> list[HealthAlert]:
    found = []

    def warn(check: HealthCheck, detail: str) -> None:
        found.append(health_alert(check, HealthSeverity.WARNING, detail))

    if above(measured.kl_to_starting_policy, thresholds.max_kl_to_starting_policy):
        warn(
            HealthCheck.KL_TO_STARTING_POLICY,
            f"KL to the starting policy {measured.kl_to_starting_policy:.3g} per token > "
            f"{thresholds.max_kl_to_starting_policy:.3g}: the policy moves fast (learning rate, passes per phase).",
        )
    if above(measured.clip_fraction, thresholds.max_clip_fraction):
        warn(
            HealthCheck.CLIP_FRACTION,
            f"Clip fraction {measured.clip_fraction:.3g} > {thresholds.max_clip_fraction:.3g}: the updates are large "
            "for the clip range (learning rate, passes per phase).",
        )
    if below(measured.distinct_samples_per_expansion, thresholds.min_distinct_samples_per_expansion):
        warn(
            HealthCheck.DISTINCT_SAMPLES,
            f"{measured.distinct_samples_per_expansion:.2f} distinct blocks per expansion < "
            f"{thresholds.min_distinct_samples_per_expansion:.2f}: the samples collapse onto fewer answers.",
        )
    explanation = measured.mean_explanation_tokens
    if below(explanation, thresholds.min_explanation_tokens) or above(explanation, thresholds.max_explanation_tokens):
        warn(
            HealthCheck.EXPLANATION_LENGTH,
            f"Mean explanation {explanation:.0f} tokens, outside {thresholds.min_explanation_tokens:.0f}-"
            f"{thresholds.max_explanation_tokens:.0f}: the visible reasoning drifts.",
        )
    if above(measured.cut_off_share, thresholds.max_cut_off_share):
        warn(
            HealthCheck.CUT_OFF_SAMPLES,
            f"{measured.cut_off_share:.1%} of the samples cut off at the token cap > "
            f"{thresholds.max_cut_off_share:.1%} ({measured.repetition_loop_share:.1%} repetition loops).",
        )
    valid = measured.held_out_valid_rate
    if below(valid, thresholds.stop_held_out_valid_rate):
        found.append(
            health_alert(
                HealthCheck.HELD_OUT_VALID_LEAN,
                HealthSeverity.STOP,
                f"Held-out valid-Lean rate {valid:.1%} < {thresholds.stop_held_out_valid_rate:.1%} "
                f"({config.stop_held_out_valid_fraction:.0%} of version 0's): the loop stops after this phase.",
            )
        )
    elif below(valid, thresholds.min_held_out_valid_rate):
        warn(
            HealthCheck.HELD_OUT_VALID_LEAN,
            f"Held-out valid-Lean rate {valid:.1%} < {thresholds.min_held_out_valid_rate:.1%} "
            f"({config.min_held_out_valid_fraction:.0%} of version 0's).",
        )
    if below(measured.held_out_success, thresholds.min_held_out_success):
        warn(
            HealthCheck.HELD_OUT_SUCCESS,
            f"Held-out per-sample success {measured.held_out_success:.1%} < {thresholds.min_held_out_success:.1%} "
            f"({config.min_held_out_success_fraction:.0%} of version 0's).",
        )
    if budget.recent_phases >= config.late_solve_phases and above(
        budget.recent_late_solve_share, config.max_late_solve_share
    ):
        found.append(
            health_alert(
                HealthCheck.SEARCH_BUDGET,
                HealthSeverity.NOTE,
                f"{budget.recent_late_solve_share:.1%} of the solves of the last {budget.recent_phases} phases came in "
                f"the last quarter of the {budget.expansion_budget}-expansion budget "
                f"(> {config.max_late_solve_share:.0%}): harder proofs may need more expansions; consider raising "
                "[sampling] max_expansions.",
            )
        )
    return found


def phase_health(
    phase: int,
    policy_version: int,
    measured: HealthMeasurements,
    history: Sequence[PhaseHealth],
    version_zero: HeldOutRates | None,
    budget: BudgetPhase,
    config: HealthConfig,
) -> PhaseHealth:
    """`history`: the earlier phases' records (`read_health_history`)."""
    earlier = [record for record in history if record.phase < phase]
    thresholds = health_thresholds(config, reference_measurements(earlier, config.reference_phases), version_zero)
    alerts = health_alerts(measured, thresholds, budget, config)
    hard_stop = any(alert.severity == HealthSeverity.STOP for alert in alerts)
    last_good = last_good_version(earlier)
    if measured.held_out_valid_rate is not None and not hard_stop:
        last_good = policy_version
    return PhaseHealth(phase, policy_version, measured, thresholds, tuple(alerts), hard_stop, last_good)


def last_good_version(history: Sequence[PhaseHealth]) -> int:
    return history[-1].last_good_version if history else 0


def read_health_history(path: Path) -> list[PhaseHealth]:
    """One record per phase in phase order, the last written for a phase whose check ran again after a restart."""
    if not path.exists():
        return []
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = from_json_object(PhaseHealth, json.loads(line))
            records[record.phase] = record
    return [records[phase] for phase in sorted(records)]


def append_health(path: Path, record: PhaseHealth) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(to_json(record) + "\n")


def health_stop_text(stop: HealthStop) -> str:
    return (
        f"The loop stopped after phase {stop.phase} on its health check: {stop.reason} "
        f"Version {stop.last_good_version} is the last good one. Roll back to it (grpo_loop.py rollback: its policy "
        "adapter as a new version), or keep the current version (grpo_loop.py clear-health-stop); then start the loop "
        "again."
    )


def read_health_stop(path: Path) -> HealthStop | None:
    if not path.exists():
        return None
    return from_json_object(HealthStop, json.loads(path.read_text(encoding="utf-8")))


def write_health_stop(path: Path, record: PhaseHealth) -> HealthStop:
    reason = " ".join(alert.detail for alert in record.alerts if alert.severity == HealthSeverity.STOP)
    stop = HealthStop(
        record.phase,
        record.policy_version,
        record.last_good_version,
        reason,
        datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    )
    path.write_text(to_json(stop), encoding="utf-8")
    return stop


def clear_health_stop(path: Path) -> Path:
    """Keeps the stop beside it as health_stop_<time>.json; the loop may start again."""
    stop = read_health_stop(path)
    assert stop is not None, path
    kept = path.with_name(f"{path.stem}_{stop.stopped_at.replace(':', '')}{path.suffix}")
    path.replace(kept)
    return kept


def publish_rollback(paths: LoopPaths, publisher: Publisher, version: int) -> ModelVersion:
    """The next version: the given version's policy adapter, the current value adapter (the policy collapsed, not the
    value model). The next phase continues training from that policy adapter."""
    versions = read_versions(paths)
    current = versions[-1]
    target = next(entry for entry in versions if entry.version == version)
    rolled_back = ModelVersion(
        version=current.version + 1,
        policy_adapter=target.policy_adapter,
        value_adapter=current.value_adapter,
        published_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        trigger=f"rollback to v{version}",
    )
    prepared = publisher.prepare(rolled_back)
    record_published(paths, prepared)
    publisher.prune(prepared)
    return prepared
