"""The loop's side of its expert-iteration rounds (rl/README.md, "Expert iteration inside the loop"): a phase's round
from the recipe, the build's verdict on it, what its record holds and the checks of the recipe at the loop's start."""

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.monitoring.families import ExpertIterationPhase
from lean_search.rl.expert_iteration_data import MAX_REPLAY_LOSS_RISE, BuildSummary, ExpertIterationConfig
from lean_search.rl.loop_config import GrpoLoopConfig, PolicyUpdate, offset_number_seed, offset_seed
from lean_search.rl.training_phase import PhaseOutcome, TrainingPhaseConfig
from lean_search.training.resident import resident_structure

# In the round's directory (`GrpoLoopPaths.expert_iteration_round`), beside the build's files.
ROUND_CONFIG_FILE = "round.toml"


@dataclass(frozen=True)
class ExpertIterationRound:
    """A phase's round once its data is built: its config (sent to the trainer when it trains), the build, and the
    seconds the build took in this session (none when a restart found it built)."""

    config: Path
    summary: BuildSummary
    trains: bool
    build_seconds: float


def round_config(
    recipe: ExpertIterationConfig,
    loop_name: str,
    run_name: str,
    directory: Path,
    phase: int,
    window_phases: int,
    current: ModelVersion,
    seed_offset: int,
) -> ExpertIterationConfig:
    """The phase's round: the window of `window_phases` phases ending at it, its data in `directory`, the published
    policy adapter to continue, and per-phase seeds that `seed_offset` moves: at offset 0 the selection's and the
    replay's are the recipe's with "/phase-<k>" appended and the trainer's is the phase number, as GRPO's."""
    data = dataclasses.replace(
        recipe.data,
        loop=loop_name,
        last_phase=phase,
        window_phases=window_phases,
        seed=offset_seed(f"{recipe.data.seed}/phase-{phase}", seed_offset),
    )
    replay = dataclasses.replace(recipe.replay, seed=offset_seed(f"{recipe.replay.seed}/phase-{phase}", seed_offset))
    optimization = dataclasses.replace(recipe.sft.optimization, seed=offset_number_seed(phase, seed_offset))
    sft = dataclasses.replace(
        recipe.sft, data=str(directory), initial_adapter=current.policy_adapter, optimization=optimization
    )
    return dataclasses.replace(recipe, run_name=run_name, data=data, replay=replay, sft=sft)


def built_for(summary: BuildSummary | None, config: ExpertIterationConfig) -> bool:
    """A build of this round's window, so a restart need not build it again."""
    return summary is not None and (summary.last_phase, summary.window_phases) == (
        config.data.last_phase,
        config.data.window_phases,
    )


def round_text(phase: int, built: ExpertIterationRound, minimum_examples: int, grpo: bool) -> str:
    summary = built.summary
    verdict = (
        "it trains"
        if built.trains
        else (
            f"too few to train (at least {minimum_examples}): the phase publishes the policy "
            + ("with its GRPO update alone" if grpo else "unchanged")
        )
    )
    return (
        f"Expert-iteration round of phase {phase}, built in {built.build_seconds:.0f} s: phases "
        f"{summary.first_phase}-{summary.last_phase}, samples of "
        f"versions {summary.minimum_version} on without {list(summary.rejected_versions)}, {summary.trees:,} solved "
        f"trees, {summary.data.train_examples:,} training and {summary.data.validation_examples:,} validation "
        f"examples; {verdict}"
    )


def round_record(summary: BuildSummary, outcome: PhaseOutcome) -> ExpertIterationPhase:
    """The round's line of the `expert_iteration` family: a skipped round's data alone."""
    record = ExpertIterationPhase(
        first_phase=summary.first_phase,
        last_phase=summary.last_phase,
        minimum_version=summary.minimum_version,
        solved_trees=summary.trees,
        examples=summary.data.train_examples,
        validation_examples=summary.data.validation_examples,
        skipped=outcome.expert_iteration is None,
    )
    if outcome.expert_iteration is None:
        return record
    result = outcome.expert_iteration.result
    change = result.parameter_change
    phase_change = outcome.expert_iteration.phase_parameter_change
    grpo = None if outcome.policy is None else outcome.policy.result
    return dataclasses.replace(
        record,
        lean_replay_examples=result.lean_replay_examples,
        math_replay_examples=result.math_replay_examples,
        optimizer_steps=result.steps,
        trained_tokens=result.trained_tokens,
        tokens=result.tokens,
        mean_loss=result.mean_loss,
        parameter_change_norm=None if change is None else change.norm,
        relative_parameter_change=None if change is None else change.relative,
        mean_gradient_norm=result.mean_gradient_norm,
        replay_loss_change=result.replay_loss_change,
        phase_parameter_change_norm=None if phase_change is None else phase_change.norm,
        phase_relative_parameter_change=None if phase_change is None else phase_change.relative,
        phase_optimizer_steps=result.steps + (0 if grpo is None else grpo.steps),
        phase_trained_tokens=result.trained_tokens + (0 if grpo is None else grpo.trained_tokens),
        training_seconds=result.training_seconds,
    )


def optional(value: float | None, digits: str = ".4g") -> str:
    return "-" if value is None else format(value, digits)


def round_update_text(phase: int, record: ExpertIterationPhase) -> str:
    """The round's step beside GRPO's `Policy update of phase <k>` line."""
    if record.skipped:
        return f"Expert-iteration update of phase {phase}: skipped, {record.examples} examples"
    return (
        f"Expert-iteration update of phase {phase}: {record.optimizer_steps} optimizer steps, "
        f"{record.trained_tokens:,} trained tokens, {record.examples} examples with {record.lean_replay_examples} Lean "
        f"and {record.math_replay_examples} math replay; parameter change {optional(record.parameter_change_norm)} "
        f"({optional(record.relative_parameter_change, '.3%')} of the start), mean gradient norm "
        f"{optional(record.mean_gradient_norm)}, mean loss {optional(record.mean_loss)}, replay validation loss "
        f"{optional(record.replay_loss_change, '+.1%')}; the phase's whole update: "
        f"{optional(record.phase_parameter_change_norm)} ({optional(record.phase_relative_parameter_change, '.3%')}), "
        f"{record.phase_optimizer_steps} steps, {record.phase_trained_tokens:,} trained tokens"
    )


def replay_loss_alert(phase: int, record: ExpertIterationPhase) -> str | None:
    """The hand-run screen's forgetting limit, an alert only: nothing changes on its own."""
    if record.replay_loss_change is None or record.replay_loss_change <= MAX_REPLAY_LOSS_RISE:
        return None
    return (
        f"Alert: phase {phase}'s expert-iteration round raised the replay validation loss by "
        f"{record.replay_loss_change:+.1%} (the hand-run round's limit: {MAX_REPLAY_LOSS_RISE:.0%}); nothing "
        "changes on its own"
    )


def recipe_refusals(config: GrpoLoopConfig, template: TrainingPhaseConfig, recipe: ExpertIterationConfig) -> list[str]:
    """What in the rounds' recipe the loop would overwrite or could not train: the window and the data's place are the
    loop's, the round continues the loop's policy on its base, and with GRPO it shares the resident policy, so the
    same model structure."""
    refusals = []
    data = recipe.data
    if (data.last_phase, data.window_phases, data.tree_directories, data.loop) != (0, 0, (), ""):
        refusals.append(
            "the recipe's [data] window and trees are the loop's (training.expert_iteration_window_phases): leave "
            "last_phase, window_phases, tree_directories and loop unset"
        )
    if recipe.sft.data or recipe.sft.initial_adapter:
        refusals.append("the recipe's [sft] data and initial_adapter are the loop's: leave them empty")
    if recipe.sft.model != config.serving.policy_base_model:
        refusals.append(f"the recipe trains {recipe.sft.model}, not the policy base {config.serving.policy_base_model}")
    policy = template.policy
    base = config.serving.policy_base_model
    if config.training.policy_update == PolicyUpdate.GRPO_AND_EXPERT_ITERATION and (
        policy is None
        or resident_structure(base, policy.optimization) != resident_structure(base, recipe.sft.optimization)
    ):
        refusals.append(
            "GRPO and the rounds train one resident policy: the phase config needs a policy section with the recipe's "
            "method, packing, gradient checkpointing and compiled layers"
        )
    return refusals
