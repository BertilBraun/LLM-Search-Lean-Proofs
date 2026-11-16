"""Step 2 of the follow-up study, the learning rates (DESIGN.md, "Follow-up study: controlled arms", "Step 2", with the
owner's decisions of 2026-11-16: no probe or gate-set runs, the rates picked on the 512 held-out states alone, no B1),
as the study driver (deployment/study_chain.sh) runs it through experiments/learning_rate_step.py.

Ten training rounds, each from v0 on the shared sampling run's slices: per-tactic GRPO (A) and pure proof success (B2)
on slice 4 at 2e-5, 5e-5 and 1e-4, expert iteration (C) at 5e-5 and 1e-4 on slice 4 (window 1) and slices 1-4 (window
4). A GRPO round's phase config and a round's recipe are what the arm's overlay gives at that rate (study_configs), so
the arm later trains exactly as its chosen variant did. Each variant's held-out run is compared with v0's own run under
the same code and mode; C's window is chosen with its rate, by the same rule over its four variants.
"""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.arm_comparison import multiple_comparisons_note
from lean_search.rl.expert_iteration_data import (
    ExpertIterationConfig,
    TrainingSummary,
    parse_expert_iteration_config,
)
from lean_search.rl.probe_rating import DifferenceInterval
from lean_search.rl.rate_ranking import HeldOutStates, RateChoice, VariantReport, includes_zero
from lean_search.rl.study_configs import OverlayKind, merged, overlay_configs
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.search.config import RunConfig
from lean_search.search.summary import markdown_table

SLICES = 4
RUN_PREFIX = "step2_"
V0_HELD_OUT = f"{RUN_PREFIX}v0"


class Signal(StrEnum):
    A = "A"
    B2 = "B2"
    C = "C"


class RoundKind(StrEnum):
    GRPO = "grpo"
    EXPERT_ITERATION = "expert_iteration"


@dataclass(frozen=True)
class StepVariant:
    signal: Signal
    # As written in the report and the run names, e.g. "5e-5".
    rate: str
    # C's window in slices; 0 for a GRPO signal, which trains on the last slice.
    window: int = 0

    @property
    def learning_rate(self) -> float:
        return float(self.rate)

    @property
    def label(self) -> str:
        return f"{self.signal}_w{self.window}_{self.rate}" if self.window else f"{self.signal}_{self.rate}"

    @property
    def run_name(self) -> str:
        return f"{RUN_PREFIX}{self.label}"

    @property
    def kind(self) -> RoundKind:
        match self.signal:
            case Signal.A | Signal.B2:
                return RoundKind.GRPO
            case Signal.C:
                return RoundKind.EXPERT_ITERATION

    @property
    def slices(self) -> tuple[int, ...]:
        return tuple(range(SLICES - max(self.window, 1) + 1, SLICES + 1))

    @property
    def build_name(self) -> str:
        """The expert-iteration data both rates of a window train on, under $LEAN_SEARCH_DATA/grpo_expert_iteration."""
        assert self.kind == RoundKind.EXPERT_ITERATION
        return f"{RUN_PREFIX}{self.signal}_w{self.window}"


# In ranking order within a signal: on a tie the rule takes the lower rate, the first listed among equal rates, so C's
# window 1 wins a tie with window 4 at the same rate.
STEP_VARIANTS = (
    StepVariant(Signal.A, "2e-5"),
    StepVariant(Signal.A, "5e-5"),
    StepVariant(Signal.A, "1e-4"),
    StepVariant(Signal.B2, "2e-5"),
    StepVariant(Signal.B2, "5e-5"),
    StepVariant(Signal.B2, "1e-4"),
    StepVariant(Signal.C, "5e-5", window=1),
    StepVariant(Signal.C, "5e-5", window=4),
    StepVariant(Signal.C, "1e-4", window=1),
    StepVariant(Signal.C, "1e-4", window=4),
)


def signal_variants(signal: Signal) -> tuple[StepVariant, ...]:
    return tuple(variant for variant in STEP_VARIANTS if variant.signal == signal)


def slice_directory(shared_run: str, slice_number: int) -> str:
    """Relative to $LEAN_SEARCH_RUNS: where experiments/slice_trees.py put the slice."""
    return f"{shared_run}/slices/slice_{slice_number}"


@dataclass(frozen=True)
class StudyTemplates:
    """The parsed files a round's config comes from: the follow-up base, its phase template, the rounds' recipe and
    the arms' overlays by signal."""

    base: Mapping[str, object]
    phase_template: Mapping[str, object]
    recipe: Mapping[str, object]
    arms: Mapping[Signal, Mapping[str, object]]


def grpo_phase_config(variant: StepVariant, templates: StudyTemplates) -> dict[str, object]:
    """The arm's phase config at the variant's rate: the shipped phase of its credit, v0 as start and KL reference."""
    assert variant.kind == RoundKind.GRPO
    rate = {"phase": {"policy": {"optimization": {"learning_rate": variant.learning_rate}}}}
    overlay = merged(templates.arms[variant.signal], rate)
    return overlay_configs(OverlayKind.ARM, overlay, templates.base, templates.phase_template, "phase.toml").phase


def expert_iteration_round(variant: StepVariant, templates: StudyTemplates, shared_run: str) -> ExpertIterationConfig:
    """Arm C's recipe at the variant's rate, on the variant's slices of the shared run (every tree, all sampled by v0),
    continuing the shared run's current policy (v0), with the recipe's own seeds."""
    assert variant.kind == RoundKind.EXPERT_ITERATION
    choices = {
        "loop": {"training": {"expert_iteration_window_phases": variant.window}},
        "expert_iteration": {"sft": {"optimization": {"learning_rate": variant.learning_rate}}},
    }
    configs = overlay_configs(
        OverlayKind.ARM,
        merged(templates.arms[variant.signal], choices),
        templates.base,
        templates.phase_template,
        "phase.toml",
        templates.recipe,
        "expert_iteration.toml",
    )
    assert configs.expert_iteration is not None
    recipe = parse_expert_iteration_config(toml_text(configs.expert_iteration))
    directories = tuple(slice_directory(shared_run, number) for number in variant.slices)
    data = dataclasses.replace(recipe.data, loop=shared_run, tree_directories=directories)
    sft = dataclasses.replace(recipe.sft, data=variant.build_name)
    return dataclasses.replace(recipe, run_name=variant.run_name, data=data, sft=sft)


def round_config_text(variant: StepVariant, templates: StudyTemplates, shared_run: str) -> str:
    match variant.kind:
        case RoundKind.GRPO:
            return toml_text(grpo_phase_config(variant, templates))
        case RoundKind.EXPERT_ITERATION:
            return toml_text(dataclasses.asdict(expert_iteration_round(variant, templates, shared_run)))


def round_adapter(variant: StepVariant, checkpoints: Path) -> Path:
    match variant.kind:
        case RoundKind.GRPO:
            return checkpoints / variant.run_name / "policy" / "adapter"
        case RoundKind.EXPERT_ITERATION:
            return checkpoints / variant.run_name / "adapter"


def round_completion_files(variant: StepVariant, checkpoints: Path) -> tuple[Path, ...]:
    """What a finished round leaves, written last by the trainer: without them the output is a half-trained one."""
    match variant.kind:
        case RoundKind.GRPO:
            return (checkpoints / variant.run_name / "phase.json", round_adapter(variant, checkpoints))
        case RoundKind.EXPERT_ITERATION:
            return (checkpoints / variant.run_name / "training_summary.json", round_adapter(variant, checkpoints))


@dataclass(frozen=True)
class PlanFiles:
    """The driver's tab-separated plan: one line per round, per expert-iteration build, per held-out run."""

    rounds: str
    builds: str
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


# bash's read joins adjacent tabs (a tab is IFS white space), so an empty field would shift the ones after it.
NO_VALUE = "-"


def tsv_lines(rows: Sequence[Sequence[object]]) -> str:
    return "".join("\t".join(str(field) for field in row) + "\n" for row in rows)


def plan_files(paths: PlanPaths) -> PlanFiles:
    """rounds.tsv: label, kind, config, run name, output directory, then for GRPO the trees and the two replay files
    (`NO_VALUE` otherwise), last the completion files, space separated; builds.tsv: build name, a config of it;
    held_out.tsv: name, arm, phase, policy adapter, v0 first."""
    rounds = []
    builds: dict[str, Path] = {}
    for variant in STEP_VARIANTS:
        config = paths.configs / f"{variant.label}.toml"
        match variant.kind:
            case RoundKind.GRPO:
                inputs = [paths.runs / slice_directory(paths.shared_run, SLICES), paths.lean_replay, paths.math_replay]
            case RoundKind.EXPERT_ITERATION:
                inputs = [NO_VALUE] * 3
                builds.setdefault(variant.build_name, config)
        completion = " ".join(str(path) for path in round_completion_files(variant, paths.checkpoints))
        output = paths.checkpoints / variant.run_name
        rounds.append([variant.label, variant.kind, config, variant.run_name, output, *inputs, completion])
    held_out = [[V0_HELD_OUT, "v0", 0, paths.v0_adapter]]
    held_out += [
        [variant.run_name, variant.label, 1, round_adapter(variant, paths.checkpoints)] for variant in STEP_VARIANTS
    ]
    return PlanFiles(tsv_lines(rounds), tsv_lines(list(builds.items())), tsv_lines(held_out))


def rank_arguments(signal: Signal) -> list[str]:
    """experiments/rank_learning_rates.py's arguments for the signal's variants against v0, without gate runs."""
    arguments = ["--v0", V0_HELD_OUT]
    for variant in signal_variants(signal):
        arguments += ["--variant", variant.label, variant.rate, variant.run_name]
    return arguments


DRY_RUN_STEPS = re.compile(r"(\d+) steps on (\d+) GPUs")
DRY_RUN_REFUSAL = "train would refuse: "


def dry_run_steps(text: str) -> int:
    """The optimizer steps grpo_expert_iteration.py train --dry-run planned; ValueError when it would refuse or plans
    none, since the real round would then fail or not train."""
    refusals = [line for line in text.splitlines() if line.startswith(DRY_RUN_REFUSAL)]
    if refusals:
        raise ValueError("; ".join(line.removeprefix(DRY_RUN_REFUSAL) for line in refusals))
    found = DRY_RUN_STEPS.findall(text)
    if not found:
        raise ValueError("The dry run printed no step count.")
    steps = int(found[-1][0])
    if steps == 0:
        raise ValueError("The dry run plans no optimizer step: the round would not train.")
    return steps


CHOSEN_LINE = re.compile(r"^Chosen: (\S+) \(", re.MULTILINE)


def chosen_label(rank_text: str) -> str:
    """The variant experiments/rank_learning_rates.py chose, from its output."""
    found = CHOSEN_LINE.findall(rank_text)
    if len(found) != 1:
        raise ValueError(f"Expected one 'Chosen:' line in the ranking's output, found {len(found)}.")
    return found[0]


@dataclass(frozen=True)
class SignalRanking:
    signal: Signal
    reports: tuple[VariantReport, ...]
    choice: RateChoice


@dataclass(frozen=True)
class ArmValues:
    """What the arms' PLACEHOLDERs take (arms/A.toml, B2.toml, C.toml, D.toml)."""

    a_rate: str
    b2_rate: str
    c_rate: str
    c_window: int


def chosen_variant(ranking: SignalRanking) -> StepVariant:
    return next(variant for variant in signal_variants(ranking.signal) if variant.label == ranking.choice.chosen)


def arm_values(rankings: Sequence[SignalRanking]) -> ArmValues:
    chosen = {ranking.signal: chosen_variant(ranking) for ranking in rankings}
    assert set(chosen) == set(Signal), chosen
    return ArmValues(chosen[Signal.A].rate, chosen[Signal.B2].rate, chosen[Signal.C].rate, chosen[Signal.C].window)


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


@dataclass(frozen=True)
class ExpertIterationRoundSize:
    expert_iteration_examples: int
    lean_replay_examples: int
    math_replay_examples: int
    dry_run_steps: int
    steps: int
    tokens: int
    training_seconds: float
    replay_loss_change: float | None


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


def expert_iteration_round_size(summary: TrainingSummary, planned_steps: int) -> ExpertIterationRoundSize:
    return ExpertIterationRoundSize(
        summary.expert_iteration_examples,
        summary.lean_replay_examples,
        summary.math_replay_examples,
        planned_steps,
        summary.steps,
        summary.tokens,
        summary.training_seconds,
        summary.replay_loss_change,
    )


@dataclass(frozen=True)
class RoundRecord:
    variant: StepVariant
    size: GrpoRoundSize | ExpertIterationRoundSize
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
    reasoning = "visible reasoning" if run_config.policy.visible_reasoning else "no visible reasoning"
    return (
        f"{reasoning}, {max_expansions} expansions per training search ({search_config}: depth weight "
        f"{run_config.priority.depth_weight:g}, depth cap {run_config.search.max_depth})"
    )


@dataclass(frozen=True)
class V0Baseline:
    """v0's run of this step against the 2026-11-15 run (older code, another pinning), paired per state."""

    current: RunRates
    earlier: RunRates | None
    valid: DifferenceInterval | None
    success: DifferenceInterval | None
    visible_reasoning: bool


@dataclass(frozen=True)
class StepReport:
    revision: str
    mode: str
    sampled_tokens: int
    lost_tokens: int
    rankings: tuple[SignalRanking, ...]
    rounds: tuple[RoundRecord, ...]
    baseline: V0Baseline
    # Wall seconds by the driver's step names (timings.tsv).
    durations: Mapping[str, float]


def points(interval: DifferenceInterval) -> str:
    return f"{100 * interval.difference:+.1f} [{100 * interval.lower:+.1f}, {100 * interval.upper:+.1f}]"


def hours(seconds: float | None) -> str:
    return "-" if seconds is None else f"{seconds / 3600:.2f} h"


def values_section(values: ArmValues) -> str:
    rows = [
        ["arms/A.toml", "phase.policy.optimization.learning_rate", values.a_rate],
        ["arms/B2.toml", "phase.policy.optimization.learning_rate", values.b2_rate],
        ["arms/C.toml", "loop.training.expert_iteration_window_phases", values.c_window],
        ["arms/C.toml", "expert_iteration.sft.optimization.learning_rate", values.c_rate],
        ["arms/D.toml", "loop.training.expert_iteration_window_phases", values.c_window],
        ["arms/D.toml", "phase.policy.optimization.learning_rate", values.a_rate],
        ["arms/D.toml", "expert_iteration.sft.optimization.learning_rate", values.c_rate],
    ]
    return "## Values for the arms (not applied: the orchestrator fills the PLACEHOLDERs)\n\n" + markdown_table(
        ["File", "Setting", "Value"], rows
    )


def ranking_section(ranking: SignalRanking) -> str:
    rows = [
        [
            report.label,
            f"{report.learning_rate:g}",
            points(report.valid),
            points(report.success),
            "no" if includes_zero(report.success) else "yes",
        ]
        for report in ranking.reports
    ]
    headers = ["Variant", "Rate", "Valid Lean, points [95%]", "Success, points [95%]", "Success apart from v0"]
    choice = ranking.choice
    lines = [
        f"## Signal {ranking.signal}: chosen {choice.chosen}",
        f"Each variant minus v0, paired per held-out state. Rule: {choice.reason}; tied with the best: "
        f"{', '.join(choice.tied)}.",
        markdown_table(headers, rows),
    ]
    chosen = next(report for report in ranking.reports if report.label == choice.chosen)
    if includes_zero(chosen.success):
        lines.append(
            "The chosen variant's success is within noise of v0's on the held-out states: one round at this rate may "
            "be a step too small to see here, not evidence that the signal does nothing."
        )
    return "\n\n".join(lines)


def round_rows(rounds: Sequence[RoundRecord]) -> tuple[list[list[object]], list[list[object]]]:
    grpo_rows: list[list[object]] = []
    expert_iteration_rows: list[list[object]] = []
    for record in rounds:
        match record.size:
            case GrpoRoundSize() as size:
                grpo_rows.append(
                    [
                        record.variant.label,
                        size.trees,
                        size.groups,
                        size.sequences,
                        size.steps,
                        f"{size.trained_tokens:,}",
                        f"{size.kl_to_reference:.4f}",
                        f"{size.clip_fraction:.3f}",
                        hours(size.trainer_seconds),
                        hours(record.wall_seconds),
                    ]
                )
            case ExpertIterationRoundSize() as size:
                change = "-" if size.replay_loss_change is None else f"{size.replay_loss_change:+.1%}"
                expert_iteration_rows.append(
                    [
                        record.variant.label,
                        f"{size.expert_iteration_examples:,}",
                        f"{size.lean_replay_examples:,} / {size.math_replay_examples:,}",
                        size.dry_run_steps,
                        size.steps,
                        f"{size.tokens:,}",
                        change,
                        hours(size.training_seconds),
                        hours(record.wall_seconds),
                    ]
                )
    return grpo_rows, expert_iteration_rows


def rounds_section(rounds: Sequence[RoundRecord]) -> str:
    grpo_rows, expert_iteration_rows = round_rows(rounds)
    grpo_headers = [
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
    expert_iteration_headers = [
        "Round",
        "Examples",
        "Lean / math replay",
        "Steps (dry run)",
        "Steps",
        "Tokens",
        "Replay loss change",
        "Training",
        "Wall",
    ]
    return "\n\n".join(
        [
            "## Rounds",
            "GRPO, slice 4, one pass, from v0:",
            markdown_table(grpo_headers, grpo_rows),
            "Expert iteration, from v0 (window 1: slice 4; window 4: slices 1-4):",
            markdown_table(expert_iteration_headers, expert_iteration_rows),
        ]
    )


def rates_text(rates: RunRates) -> str:
    return f"{rates.label}: valid Lean {rates.valid:.1%}, success {rates.success:.1%} ({rates.samples:,} samples)"


def baseline_section(baseline: V0Baseline) -> str:
    lines = [
        "## v0's held-out baseline",
        "v0 was run again in this step (`held_out_step2_v0`), under the step's code, sampling mode, servers and CPU "
        "layout, and every variant is paired with that run. The 2026-11-15 run (`held_out_v0`) was made on older code, "
        "with the Lean side pinned to 48 CPUs instead of 96, and with visible reasoning whatever the arms' mode; a "
        "baseline differing from its variants in anything but the adapter would bias every comparison, and the rerun "
        "costs about ten minutes.",
        rates_text(baseline.current),
    ]
    if baseline.earlier is not None:
        lines.append(rates_text(baseline.earlier))
    if baseline.valid is not None and baseline.success is not None:
        caveat = (
            ""
            if baseline.visible_reasoning
            else " Not an A/A check: the step's mode samples without visible reasoning, the earlier run with it."
        )
        lines.append(
            f"This step's v0 minus the earlier run, paired per state (descriptive): valid Lean "
            f"{points(baseline.valid)}, success {points(baseline.success)} points.{caveat}"
        )
    return "\n\n".join(lines)


DURATION_STEPS = (
    ("s1_sampling", "Shared sampling (48M tokens)"),
    ("s1_slices", "Slices"),
    (f"held_out_{V0_HELD_OUT}", "v0's held-out run"),
)


def durations_section(report: StepReport) -> str:
    rows = [[title, hours(report.durations.get(name))] for name, title in DURATION_STEPS]
    rounds = [report.durations.get(f"round_{variant.label}") for variant in STEP_VARIANTS]
    held_out = [report.durations.get(f"held_out_{variant.run_name}") for variant in STEP_VARIANTS]
    builds = sorted(name for name in report.durations if name.startswith("build_"))
    rows += [
        [f"Expert-iteration data {name.removeprefix('build_')} (beside the GRPO rounds)", hours(report.durations[name])]
        for name in builds
    ]
    rows.append(["Training rounds, together", hours(sum(seconds for seconds in rounds if seconds is not None))])
    rows.append(
        ["Variants' held-out runs, together", hours(sum(seconds for seconds in held_out if seconds is not None))]
    )
    return "## Durations (wall clock of the driver)\n\n" + markdown_table(["Part", "Wall"], rows)


def report_markdown(report: StepReport) -> str:
    values = arm_values(report.rankings)
    intervals = sum(2 * len(ranking.reports) for ranking in report.rankings)
    sections = [
        "# Step 2: learning rates",
        f"Code {report.revision}. Sampling mode: {report.mode}. Shared sampling: {report.sampled_tokens:,} generated "
        f"tokens counted, {report.lost_tokens:,} lost. Every variant is one round from v0; the 512 held-out states "
        "decide (no probe or gate-set runs; owner, 2026-11-16).",
        values_section(values),
        *(ranking_section(ranking) for ranking in report.rankings),
        multiple_comparisons_note(intervals),
        rounds_section(report.rounds),
        baseline_section(report.baseline),
        durations_section(report),
    ]
    return "\n\n".join(sections) + "\n"
