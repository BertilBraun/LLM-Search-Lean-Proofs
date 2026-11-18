"""The follow-up study's config files: placeholders, inheritance, the arms and the shared sampling run.

A setting the study fills in later is a string starting with PLACEHOLDER where a number or a path belongs, so the
config does not load and a launcher names what is left to set. A study evaluation config may name a `base` file it
changes (`resolved_toml`), so every one inherits probe_evaluation.toml's one probe concurrency.

An arm (experiments/configs/grpo/followup/arms/) is a thin overlay over base.toml and base.toml's phase template whose
[loop] and [phase] tables change only `ARM_SETTINGS`; an arm whose policy trains in expert-iteration rounds (C, D) also
gets the rounds' recipe (followup/expert_iteration.toml), its [expert_iteration] table changing only the learning
rate. Step 2's shared sampling run (followup/shared_sampling.toml) is one over base.toml changing only
`SHARED_SAMPLING_SETTINGS`. A smoke run (deployment/arms_chain.sh) is an arm's overlay under its own name with a
smaller budget, changing `SMOKE_SETTINGS`. experiments/followup_arm.py writes the configs the loop reads, and refuses a
result whose phases are not ended by generated tokens.

The sampling mode (followup/modes/: with or without visible reasoning, the expansions per training search) is one file
over base.toml's [sampling] that changes exactly `MODE_SETTINGS`, applied alike to the shared sampling run and every
arm (`with_sampling_mode`); an arm whose sampling (the search config's bytes included) differs from the shared run's
is refused (`sampling_refusal`), so the arms sample as the trees they took their learning rates from.
"""

import hashlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.rl.loop_config import PolicyUpdate
from lean_search.search.config import RunConfig

PLACEHOLDER = "PLACEHOLDER"
BASE_KEY = "base"


class OverlayKind(StrEnum):
    ARM = "arm"
    SHARED_SAMPLING = "shared sampling"
    # An arm's short run under its own name, before the arm runs (deployment/arms_chain.sh's smoke test).
    SMOKE = "smoke"


# An arm is base.toml and its phase template changed only here (DESIGN.md, "Arms": everything else identical, the
# token budget per phase and the phase count included).
ARM_SETTINGS = frozenset(
    {
        "loop.name",
        # A second seed (WP1's top-level seed offset).
        "loop.seed_offset",
        "phase.policy.data.credit",
        "phase.policy.optimization.learning_rate",
        # Expert-iteration rounds (arms C, D): instead of or beside GRPO, their schedule and window, their rate.
        "loop.training.policy_update",
        "loop.training.expert_iteration_every_phases",
        "loop.training.expert_iteration_window_phases",
        "expert_iteration.sft.optimization.learning_rate",
    }
)
# Step 2's shared sampling: v0 sampling without training until a total token count, a phase never due.
SHARED_SAMPLING_SETTINGS = frozenset(
    {
        "loop.name",
        "loop.training.phase_generated_tokens",
        "loop.training.max_generated_tokens",
        "loop.training.max_phases",
    }
)


# A smoke run: an arm's overlay with a smaller budget, its value model trained at its phases (rl/arms_chain.py,
# smoke_overlay).
SMOKE_SETTINGS = ARM_SETTINGS | frozenset(
    {"loop.training.phase_generated_tokens", "loop.training.max_phases", "loop.training.value_every_phases"}
)


MODE_SETTINGS = frozenset({"sampling.search_config", "sampling.max_expansions"})


def with_sampling_mode(base: Mapping[str, object], mode: Mapping[str, object]) -> dict[str, object]:
    """`base` searching as `mode` says; ValueError unless the mode sets exactly `MODE_SETTINGS`, none a placeholder."""
    keys = set(leaf_keys(mode))
    if keys != MODE_SETTINGS:
        raise ValueError(
            f"A sampling mode sets exactly {sorted(MODE_SETTINGS)}; this one misses {sorted(MODE_SETTINGS - keys)} "
            f"and adds {sorted(keys - MODE_SETTINGS)}."
        )
    left = placeholders(mode)
    if left:
        raise ValueError(f"The sampling mode still has placeholders at {left}.")
    sampling = mode["sampling"]
    assert isinstance(sampling, Mapping)
    expansions = sampling["max_expansions"]
    if not isinstance(expansions, int) or isinstance(expansions, bool) or expansions < 1:
        raise ValueError(f"The sampling mode's max_expansions must be a positive integer, not {expansions!r}.")
    return merged(base, mode)


def training_search_refusal(run_config: RunConfig) -> str | None:
    """Training searches are budgeted by [sampling] max_expansions; a per-search token cap belongs to evaluations
    (step 1's token-capped configs)."""
    cap = run_config.search.max_generated_tokens
    if cap is None:
        return None
    return f"its search config caps each search at {cap:,} generated tokens: an evaluation config, not a training one"


# Beside an arm's loop.toml: what it samples with, the search config's bytes included.
SAMPLING_RECORD_FILE = "sampling.json"


@dataclass(frozen=True)
class SamplingRecord:
    search_config: str
    max_expansions: int
    search_config_sha256: str


def sampling_record(sampling: Mapping[str, object], repository: Path) -> SamplingRecord:
    """`sampling`: a loop config's [sampling] table; its search config is read under `repository`."""
    search_config = sampling["search_config"]
    expansions = sampling["max_expansions"]
    assert isinstance(search_config, str) and isinstance(expansions, int)
    digest = hashlib.sha256((repository / search_config).read_bytes()).hexdigest()
    return SamplingRecord(search_config, expansions, digest)


def sampling_refusal(arm: SamplingRecord, shared: SamplingRecord) -> str | None:
    """An arm must sample as step 2's shared run did: the rates were chosen on those trees."""
    if arm == shared:
        return None
    return (
        f"the arm would sample with {arm}, the shared sampling run sampled with {shared}: the arms must sample in the "
        "mode their learning rates were chosen in"
    )


def overlay_settings(kind: OverlayKind) -> frozenset[str]:
    match kind:
        case OverlayKind.ARM:
            return ARM_SETTINGS
        case OverlayKind.SHARED_SAMPLING:
            return SHARED_SAMPLING_SETTINGS
        case OverlayKind.SMOKE:
            return SMOKE_SETTINGS


def placeholders(table: Mapping[str, object], prefix: str = "") -> list[str]:
    """The dotted keys of every placeholder in a parsed TOML table, arrays of tables included."""
    found = []
    for key, value in table.items():
        match value:
            case str() if value.startswith(PLACEHOLDER):
                found.append(f"{prefix}{key}")
            case Mapping():
                found += placeholders(value, f"{prefix}{key}.")
            case list():
                for index, element in enumerate(value):
                    if isinstance(element, Mapping):
                        found += placeholders(element, f"{prefix}{key}[{index}].")
                    elif isinstance(element, str) and element.startswith(PLACEHOLDER):
                        found.append(f"{prefix}{key}[{index}]")
    return found


def leaf_keys(table: Mapping[str, object], prefix: str = "") -> list[str]:
    keys = []
    for key, value in table.items():
        if isinstance(value, Mapping):
            keys += leaf_keys(value, f"{prefix}{key}.")
        else:
            keys.append(f"{prefix}{key}")
    return keys


def merged(base: Mapping[str, object], overlay: Mapping[str, object]) -> dict[str, object]:
    """`base` with `overlay`'s values in place, table by table (an array, of tables too, replaced whole)."""
    result = dict(base)
    for key, value in overlay.items():
        base_value = result.get(key)
        if isinstance(value, Mapping) and isinstance(base_value, Mapping):
            result[key] = merged(base_value, value)
        else:
            result[key] = value
    return result


def resolved_toml(path: Path, repository: Path) -> dict[str, object]:
    """The file's table over its `base` (a path relative to the repository), recursively; without one, the file."""
    table = tomllib.loads(path.read_text(encoding="utf-8"))
    base = table.pop(BASE_KEY, None)
    return table if base is None else merged(resolved_toml(repository / base, repository), table)


@dataclass(frozen=True)
class OverlayConfigs:
    # The loop config, its training.phase_config set to where the phase config goes, and that phase config; with
    # expert-iteration rounds also its training.expert_iteration_config set to where their recipe goes, and the recipe.
    loop: dict[str, object]
    phase: dict[str, object]
    expert_iteration: dict[str, object] | None = None


def budget_refusals(kind: OverlayKind, training: Mapping[str, object]) -> list[str]:
    """An arm's phases must end by generated tokens and stop after a phase count; the shared sampling run's phase must
    never come due before its total stop."""
    phase_tokens = training.get("phase_generated_tokens", 0)
    match kind:
        case OverlayKind.ARM | OverlayKind.SMOKE:
            refusals = [] if phase_tokens else ["no [training] phase_generated_tokens: phases would end on minutes"]
            if not training.get("max_phases", 0):
                refusals.append("no [training] max_phases: the arm would never stop")
            return refusals
        case OverlayKind.SHARED_SAMPLING:
            total = training.get("max_generated_tokens", 0)
            if not total:
                return ["no [training] max_generated_tokens: the sampling would never stop"]
            return [] if phase_tokens > total else ["a phase would come due before the total: it would train"]


def unused_settings(update: PolicyUpdate, overlay: Mapping[str, object]) -> list[str]:
    """An overlay's settings its policy update ignores: the rounds' without rounds, GRPO's without GRPO."""
    match update:
        case PolicyUpdate.GRPO:
            unused = ("expert_iteration.", "loop.training.expert_iteration_")
        case PolicyUpdate.EXPERT_ITERATION:
            unused = ("phase.policy.",)
        case PolicyUpdate.GRPO_AND_EXPERT_ITERATION:
            unused = ()
    return [key for key in leaf_keys(overlay) if key.startswith(unused)]


def overlay_configs(
    kind: OverlayKind,
    overlay: Mapping[str, object],
    base: Mapping[str, object],
    phase_template: Mapping[str, object],
    phase_path: str,
    expert_iteration_template: Mapping[str, object] | None = None,
    expert_iteration_path: str = "",
) -> OverlayConfigs:
    """ValueError for an overlay that changes anything but its kind's settings, still holds a placeholder, or whose
    loop config would not be budgeted by generated tokens; `expert_iteration_template` is the rounds' recipe, which an
    overlay with rounds needs."""
    allowed = overlay_settings(kind)
    unexpected = [key for key in leaf_keys(overlay) if key not in allowed]
    if unexpected:
        raise ValueError(f"A {kind} overlay changes only {sorted(allowed)}, not {unexpected}.")
    left = placeholders(overlay)
    if left:
        raise ValueError(f"The {kind} overlay still has placeholders at {left}.")
    loop = merged(base, overlay.get("loop", {}))
    training = loop["training"]
    assert isinstance(training, Mapping)
    refusals = budget_refusals(kind, training)
    if refusals:
        raise ValueError(f"The {kind}'s loop config: {'; '.join(refusals)}.")
    loop["training"] = {**training, "phase_config": phase_path}
    phase = merged(phase_template, overlay.get("phase", {}))
    contradictions = unused_settings(PolicyUpdate(training.get("policy_update", PolicyUpdate.GRPO)), overlay)
    if contradictions:
        raise ValueError(f"The {kind} sets what its policy update never reads: {contradictions}.")
    if training.get("policy_update", PolicyUpdate.GRPO) == PolicyUpdate.GRPO:
        return OverlayConfigs(loop, phase)
    assert expert_iteration_template is not None
    loop["training"] = {**loop["training"], "expert_iteration_config": expert_iteration_path}
    return OverlayConfigs(loop, phase, merged(expert_iteration_template, overlay.get("expert_iteration", {})))
