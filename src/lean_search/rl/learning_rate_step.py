"""Step 2 of the follow-up study, arm A's learning rate (DESIGN.md, "Follow-up study: controlled arms", "Step 2",
with the owner's decisions of 2026-11-17: arm B dropped, arm C takes the offline run O2's rate and a 4-phase window, D
takes C's rate and window and A's rate), as the study driver (deployment/study_chain.sh) runs it through
experiments/learning_rate_step.py.

One shared phase of sampling from v0 (12M generated tokens), then three per-tactic GRPO rounds from v0 on its trees at
2e-5, 5e-5 and 1e-4. A round's phase config is what arm A's overlay gives at that rate (study_configs): the arm trains
with its chosen variant's recipe, though not with its seeds (the template's, not the loop's per-phase ones) or its
trainer (grpo_phase.py, not the persistent one). Each variant's held-out run is compared with v0's own run under the
same code and mode, and v0 runs again after the variants as the step's A/A and drift check.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.arm_comparison import multiple_comparisons_note
from lean_search.rl.evaluation import EvaluationSummary
from lean_search.rl.probe_rating import DifferenceInterval
from lean_search.rl.rate_ranking import HeldOutStates, RateChoice, VariantReport, includes_zero
from lean_search.rl.study_configs import OverlayKind, merged, overlay_configs
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.search.config import RunConfig
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table

RUN_PREFIX = "step2_"
V0_HELD_OUT = f"{RUN_PREFIX}v0"
# v0 again after the variants: the step's A/A and drift check.
V0_END_HELD_OUT = f"{RUN_PREFIX}v0_end"
# The shared phase's trees, as experiments/slice_trees.py --slices 1 links them: every tree of the run, finished order.
TREES_SLICE = "slices/slice_1"
# Arm C's window (owner, 2026-11-17); arm D takes it.
C_WINDOW_PHASES = 4


@dataclass(frozen=True)
class StepVariant:
    # As written in the report, the run names and arms/A.toml, e.g. "5e-5".
    rate: str

    @property
    def learning_rate(self) -> float:
        return float(self.rate)

    @property
    def label(self) -> str:
        return f"A_{self.rate}"

    @property
    def run_name(self) -> str:
        return f"{RUN_PREFIX}{self.label}"


# In ranking order: on a tie the rule (rate_ranking.tie_break) takes the lower rate.
STEP_VARIANTS = (StepVariant("2e-5"), StepVariant("5e-5"), StepVariant("1e-4"))


def variant_of(label: str) -> StepVariant:
    return next(variant for variant in STEP_VARIANTS if variant.label == label)


@dataclass(frozen=True)
class StudyTemplates:
    """The parsed files a round's config comes from: the follow-up base, its phase template and arm A's overlay."""

    base: Mapping[str, object]
    phase_template: Mapping[str, object]
    arm: Mapping[str, object]


def grpo_phase_config(variant: StepVariant, templates: StudyTemplates) -> dict[str, object]:
    """Arm A's phase config at the variant's rate: per-tactic credit, v0 as start and KL reference."""
    rate = {"phase": {"policy": {"optimization": {"learning_rate": variant.learning_rate}}}}
    overlay = merged(templates.arm, rate)
    return overlay_configs(OverlayKind.ARM, overlay, templates.base, templates.phase_template, "phase.toml").phase


def round_config_text(variant: StepVariant, templates: StudyTemplates) -> str:
    return toml_text(grpo_phase_config(variant, templates))


def round_adapter(variant: StepVariant, checkpoints: Path) -> Path:
    return checkpoints / variant.run_name / "policy" / "adapter"


def round_outcome_file(variant: StepVariant, checkpoints: Path) -> Path:
    return checkpoints / variant.run_name / "phase.json"


def round_completion_files(variant: StepVariant, checkpoints: Path) -> tuple[Path, ...]:
    """What a finished round leaves, phase.json written last: without them the output is a half-trained one."""
    return (round_outcome_file(variant, checkpoints), round_adapter(variant, checkpoints))


def round_outcome_problem(variant: StepVariant, checkpoints: Path) -> str | None:
    """Why the round's phase.json does not read back as its trainer wrote it, e.g. cut short by a kill mid-write;
    None when it does."""
    path = round_outcome_file(variant, checkpoints)
    try:
        from_json_object(PhaseOutcome, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError) as error:
        return f"{path} does not read back: {error!r}"
    return None


@dataclass(frozen=True)
class PlanFiles:
    """The driver's tab-separated plan: one line per round, per held-out run."""

    rounds: str
    held_out: str


@dataclass(frozen=True)
class PlanPaths:
    configs: Path
    checkpoints: Path
    runs: Path
    shared_run: str
    v0_adapter: str
    # The loop's replay files (base.toml [training] lean_replay, math_replay), absolute.
    lean_replay: Path
    math_replay: Path


def tsv_lines(rows: Sequence[Sequence[object]]) -> str:
    return "".join("\t".join(str(field) for field in row) + "\n" for row in rows)


def plan_files(paths: PlanPaths) -> PlanFiles:
    """rounds.tsv: label, config, run name, output directory, the trees, the two replay files, the completion files
    (space separated); held_out.tsv: name, arm, phase, policy adapter, v0 first and last."""
    trees = paths.runs / paths.shared_run / TREES_SLICE
    rounds = [
        [
            variant.label,
            paths.configs / f"{variant.label}.toml",
            variant.run_name,
            paths.checkpoints / variant.run_name,
            trees,
            paths.lean_replay,
            paths.math_replay,
            " ".join(str(path) for path in round_completion_files(variant, paths.checkpoints)),
        ]
        for variant in STEP_VARIANTS
    ]
    held_out = [[V0_HELD_OUT, "v0", 0, paths.v0_adapter]]
    held_out += [
        [variant.run_name, variant.label, 1, round_adapter(variant, paths.checkpoints)] for variant in STEP_VARIANTS
    ]
    held_out.append([V0_END_HELD_OUT, "v0", 0, paths.v0_adapter])
    return PlanFiles(tsv_lines(rounds), tsv_lines(held_out))


def rank_arguments() -> list[str]:
    """experiments/rank_learning_rates.py's arguments for A's variants against v0, without gate runs."""
    arguments = ["--v0", V0_HELD_OUT]
    for variant in STEP_VARIANTS:
        arguments += ["--variant", variant.label, variant.rate, variant.run_name]
    return arguments


def dropped_states(summary_text: str) -> tuple[str, ...]:
    """The states a held-out run left without a tree (its summary.json); the run is complete only without any."""
    return from_json_object(EvaluationSummary, json.loads(summary_text)).dropped


CHOSEN_LINE = re.compile(r"^Chosen: (\S+) \(", re.MULTILINE)


def chosen_label(rank_text: str) -> str:
    """The variant experiments/rank_learning_rates.py chose, from its output."""
    found = CHOSEN_LINE.findall(rank_text)
    if len(found) != 1:
        raise ValueError(f"Expected one 'Chosen:' line in the ranking's output, found {len(found)}.")
    return found[0]


@dataclass(frozen=True)
class Ranking:
    reports: tuple[VariantReport, ...]
    choice: RateChoice


@dataclass(frozen=True)
class GrpoRoundSize:
    trees: int
    groups: int
    sequences: int
    steps: int
    trained_tokens: int
    kl_to_reference: float
    clip_fraction: float
    trainer_seconds: float


def grpo_round_size(outcome: PhaseOutcome) -> GrpoRoundSize:
    assert outcome.policy is not None
    result = outcome.policy.result
    return GrpoRoundSize(
        outcome.trees,
        outcome.groups,
        result.sequences,
        result.steps,
        result.trained_tokens,
        result.final_kl_to_reference,
        result.final_clip_fraction,
        outcome.timings.total_seconds,
    )


@dataclass(frozen=True)
class RoundRecord:
    variant: StepVariant
    size: GrpoRoundSize
    # The driver's wall clock for the round's training job (load, compile, train, save).
    wall_seconds: float


@dataclass(frozen=True)
class RunRates:
    label: str
    samples: int
    valid: float
    success: float


def run_rates(held_out: HeldOutStates) -> RunRates:
    outcomes = list(held_out.states.values())
    samples = sum(outcome.samples for outcome in outcomes)
    return RunRates(
        held_out.label,
        samples,
        sum(outcome.valid for outcome in outcomes) / samples,
        sum(outcome.successes for outcome in outcomes) / samples,
    )


def read_durations(text: str) -> dict[str, float]:
    """The driver's timings.tsv (name, start and end in epoch seconds per line); a step done again keeps its last."""
    durations = {}
    for line in text.splitlines():
        name, start, end = line.split("\t")
        durations[name] = float(end) - float(start)
    return durations


def mode_description(search_config: str, run_config: RunConfig, max_expansions: int) -> str:
    """With a warning when the depth cap can bind: each expansion's children lie one block deeper, so a search reaches
    at most its expansions (harvesting's included) in depth. A warning, not a refusal: the visible loop search's cap of
    16 binds by design at 32 + 16 expansions."""
    reasoning = "visible reasoning" if run_config.policy.visible_reasoning else "no visible reasoning"
    search = run_config.search
    reach = max_expansions + (search.harvest.max_expansions if search.harvest.enabled else 0)
    binding = (
        f"; the depth cap can bind: {reach} expansions can reach depth {reach}" if reach > search.max_depth else ""
    )
    return (
        f"{reasoning}, {max_expansions} expansions per training search ({search_config}: depth weight "
        f"{run_config.priority.depth_weight:g}, depth cap {search.max_depth}{binding})"
    )


@dataclass(frozen=True)
class PairedRun:
    """Another v0 run and its differences to the step's first v0 run, paired per state (the other minus the first)."""

    rates: RunRates
    valid: DifferenceInterval
    success: DifferenceInterval


@dataclass(frozen=True)
class V0Baseline:
    """The step's first v0 run, which every variant is paired with, its run after the variants (the A/A and drift
    check) and the 2026-11-15 run (older code, 48 Lean CPUs; descriptive), or why that one could not be compared."""

    current: RunRates
    end: PairedRun
    earlier: PairedRun | str
    visible_reasoning: bool


@dataclass(frozen=True)
class StepReport:
    revision: str
    mode: str
    sampled_tokens: int
    lost_tokens: int
    ranking: Ranking
    rounds: tuple[RoundRecord, ...]
    baseline: V0Baseline
    # Wall seconds by the driver's step names (timings.tsv).
    durations: Mapping[str, float]
    # The offline run O2's rate choice (offline_chain.sh's rank_matched.txt), which arms C and D take.
    o2_ranking: str


def points(interval: DifferenceInterval) -> str:
    return f"{100 * interval.difference:+.1f} [{100 * interval.lower:+.1f}, {100 * interval.upper:+.1f}]"


def hours(seconds: float | None) -> str:
    return "-" if seconds is None else f"{seconds / 3600:.2f} h"


def side_of_v0(interval: DifferenceInterval) -> str:
    if includes_zero(interval):
        return "within noise"
    return "above v0" if interval.lower > 0 else "below v0"


def below_v0(report: VariantReport) -> list[str]:
    """The measures on which the variant is below v0 with its 95% interval excluding 0."""
    measures = (("success", report.success), ("valid Lean", report.valid))
    return [name for name, interval in measures if side_of_v0(interval) == "below v0"]


def chosen_report(ranking: Ranking) -> VariantReport:
    return next(report for report in ranking.reports if report.label == ranking.choice.chosen)


def values_section(ranking: Ranking, o2_ranking: str) -> str:
    a_rate = variant_of(ranking.choice.chosen).rate
    o2 = f"from O2: the 'Chosen:' line of {o2_ranking}"
    rows = [
        ["arms/A.toml", "phase.policy.optimization.learning_rate", a_rate],
        ["arms/C.toml", "loop.training.expert_iteration_window_phases", f"{C_WINDOW_PHASES} (owner, 2026-11-17)"],
        ["arms/C.toml", "expert_iteration.sft.optimization.learning_rate", o2],
        ["arms/D.toml", "loop.training.expert_iteration_window_phases", f"{C_WINDOW_PHASES} (C's)"],
        ["arms/D.toml", "phase.policy.optimization.learning_rate", f"{a_rate} (A's)"],
        ["arms/D.toml", "expert_iteration.sft.optimization.learning_rate", f"C's, {o2}"],
    ]
    worse = below_v0(chosen_report(ranking))
    warnings = (
        [
            f"**Look first:** A's chosen variant {ranking.choice.chosen} is below v0 in {' and '.join(worse)}: the "
            "round made the policy worse on the held-out states."
        ]
        if worse
        else []
    )
    title = "## Values for the arms (not applied: the orchestrator fills the PLACEHOLDERs)"
    return "\n\n".join([title, *warnings, markdown_table(["File", "Setting", "Value"], rows)])


def ranking_section(ranking: Ranking) -> str:
    rows = [
        [
            report.label,
            variant_of(report.label).rate,
            points(report.valid),
            side_of_v0(report.valid),
            points(report.success),
            side_of_v0(report.success),
        ]
        for report in ranking.reports
    ]
    headers = ["Variant", "Rate", "Valid Lean, points [95%]", "Valid Lean", "Success, points [95%]", "Success"]
    choice = ranking.choice
    lines = [
        f"## Arm A: chosen {choice.chosen}",
        f"Each variant minus v0, paired per held-out state. Rule: {choice.reason}; tied with the best: "
        f"{', '.join(choice.tied)}.",
        markdown_table(headers, rows),
    ]
    chosen = chosen_report(ranking)
    worse = below_v0(chosen)
    if worse:
        lines.append(
            f"**The chosen variant is below v0 in {' and '.join(worse)}.** The rule ranks the variants against each "
            "other, not against v0: every rate may have hurt. Look before filling its value."
        )
    elif includes_zero(chosen.success):
        lines.append(
            "The chosen variant's success is within noise of v0's on the held-out states: one round at this rate may "
            "be a step too small to see here, not evidence that the signal does nothing."
        )
    return "\n\n".join(lines)


def rounds_section(rounds: Sequence[RoundRecord]) -> str:
    rows = [
        [
            record.variant.label,
            record.size.trees,
            record.size.groups,
            record.size.sequences,
            record.size.steps,
            f"{record.size.trained_tokens:,}",
            f"{record.size.kl_to_reference:.4f}",
            f"{record.size.clip_fraction:.3f}",
            hours(record.size.trainer_seconds),
            hours(record.wall_seconds),
        ]
        for record in rounds
    ]
    headers = [
        "Round",
        "Trees",
        "Groups",
        "Sequences",
        "Steps",
        "Trained tokens",
        "KL to v0",
        "Clip fraction",
        "Trainer",
        "Wall",
    ]
    return "\n\n".join(
        ["## Rounds", "Per-tactic GRPO, one pass over the shared phase, from v0:", markdown_table(headers, rows)]
    )


def rates_text(rates: RunRates) -> str:
    return f"{rates.label}: valid Lean {rates.valid:.1%}, success {rates.success:.1%} ({rates.samples:,} samples)"


def baseline_section(baseline: V0Baseline) -> str:
    end = baseline.end
    lines = [
        "## v0's held-out baseline",
        f"v0 was run again in this step (`held_out_{V0_HELD_OUT}`), under the step's code, sampling mode, servers and "
        "CPU layout, and every variant is paired with that run. The 2026-11-15 run (`held_out_v0`) was made on older "
        "code, with the Lean side pinned to 48 CPUs instead of 96, and with visible reasoning whatever the arms' "
        "mode; a baseline differing from its variants in anything but the adapter would bias every comparison, and "
        "the rerun costs about ten minutes.",
        rates_text(baseline.current),
        f"{rates_text(end.rates)}. After the variants minus before them, paired per state (the A/A and drift check): "
        f"valid Lean {points(end.valid)}, success {points(end.success)} points.",
    ]
    measures = (("valid Lean", end.valid), ("success", end.success))
    drifted = [name for name, interval in measures if not includes_zero(interval)]
    if drifted:
        lines.append(
            f"**v0 moved during the step in {' and '.join(drifted)}** (or by chance: each A/A interval excludes 0 "
            "about one time in twenty): every variant's difference to v0 may carry that drift; the ranking compares "
            "the variants with each other and is less affected."
        )
    match baseline.earlier:
        case PairedRun() as earlier:
            caveat = (
                ""
                if baseline.visible_reasoning
                else " Not an A/A check: the step's mode samples without visible reasoning, the earlier run with it."
            )
            lines.append(rates_text(earlier.rates))
            lines.append(
                f"The earlier run minus this step's v0, paired per state (descriptive): valid Lean "
                f"{points(earlier.valid)}, success {points(earlier.success)} points.{caveat}"
            )
        case str() as reason:
            lines.append(f"The earlier run is not compared: {reason}")
    return "\n\n".join(lines)


DURATION_STEPS = (
    ("s1_sampling", "Shared sampling (one phase, 12M tokens)"),
    ("s1_slices", "The phase's trees linked"),
    (f"held_out_{V0_HELD_OUT}", "v0's held-out run"),
    (f"held_out_{V0_END_HELD_OUT}", "v0's held-out run after the variants"),
)


def durations_section(report: StepReport) -> str:
    rows = [[title, hours(report.durations.get(name))] for name, title in DURATION_STEPS]
    rounds = [report.durations.get(f"round_{variant.label}") for variant in STEP_VARIANTS]
    held_out = [report.durations.get(f"held_out_{variant.run_name}") for variant in STEP_VARIANTS]
    rows.append(["Training rounds, together", hours(sum(seconds for seconds in rounds if seconds is not None))])
    rows.append(
        ["Variants' held-out runs, together", hours(sum(seconds for seconds in held_out if seconds is not None))]
    )
    return "## Durations (wall clock of the driver)\n\n" + markdown_table(["Part", "Wall"], rows)


def report_markdown(report: StepReport) -> str:
    # Each variant's two against v0, and v0's A/A pair (valid Lean, success).
    intervals = 2 * len(report.ranking.reports) + 2
    sections = [
        "# Step 2: arm A's learning rate",
        f"Code {report.revision}. Sampling mode: {report.mode}. Shared sampling: {report.sampled_tokens:,} generated "
        f"tokens counted, {report.lost_tokens:,} lost. Every variant is one per-tactic GRPO round from v0; the 512 "
        "held-out states decide (no probe or gate-set runs; owner, 2026-11-16). Arm B is dropped; arm C takes O2's "
        "rate and a 4-phase window, D takes C's rate and window and A's rate (owner, 2026-11-17).",
        values_section(report.ranking, report.o2_ranking),
        ranking_section(report.ranking),
        multiple_comparisons_note(intervals),
        rounds_section(report.rounds),
        baseline_section(report.baseline),
        durations_section(report),
    ]
    return "\n\n".join(sections) + "\n"
