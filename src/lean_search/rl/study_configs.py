"""The follow-up study's config files: placeholders, inheritance, the arms and the shared sampling run.

A setting the study fills in later is a string starting with PLACEHOLDER where a number or a path belongs, so the
config does not load and a launcher names what is left to set. A study evaluation config may name a `base` file it
changes (`resolved_toml`), so every one inherits probe_evaluation.toml's one probe concurrency.

An arm (experiments/configs/grpo/followup/arms/) is a thin overlay over base.toml and base.toml's phase template whose
[loop] and [phase] tables change only `ARM_SETTINGS`; step 2's shared sampling run (followup/shared_sampling.toml)
is one over base.toml changing only `SHARED_SAMPLING_SETTINGS`. experiments/followup_arm.py writes the configs the
loop reads, and refuses a result whose phases are not ended by generated tokens.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

PLACEHOLDER = "PLACEHOLDER"
BASE_KEY = "base"


class OverlayKind(StrEnum):
    ARM = "arm"
    SHARED_SAMPLING = "shared sampling"


# An arm is base.toml and its phase template changed only here (DESIGN.md, "Arms": everything else identical, the
# token budget per phase and the phase count included).
ARM_SETTINGS = frozenset(
    {
        "loop.name",
        # A second seed (WP1's top-level seed offset).
        "loop.seed_offset",
        "phase.policy.data.credit",
        "phase.policy.optimization.learning_rate",
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


def overlay_settings(kind: OverlayKind) -> frozenset[str]:
    match kind:
        case OverlayKind.ARM:
            return ARM_SETTINGS
        case OverlayKind.SHARED_SAMPLING:
            return SHARED_SAMPLING_SETTINGS


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
    # The loop config, its training.phase_config set to where the phase config goes, and that phase config.
    loop: dict[str, object]
    phase: dict[str, object]


def budget_refusals(kind: OverlayKind, training: Mapping[str, object]) -> list[str]:
    """An arm's phases must end by generated tokens and stop after a phase count; the shared sampling run's phase must
    never come due before its total stop."""
    phase_tokens = training.get("phase_generated_tokens", 0)
    match kind:
        case OverlayKind.ARM:
            refusals = [] if phase_tokens else ["no [training] phase_generated_tokens: phases would end on minutes"]
            if not training.get("max_phases", 0):
                refusals.append("no [training] max_phases: the arm would never stop")
            return refusals
        case OverlayKind.SHARED_SAMPLING:
            total = training.get("max_generated_tokens", 0)
            if not total:
                return ["no [training] max_generated_tokens: the sampling would never stop"]
            return [] if phase_tokens > total else ["a phase would come due before the total: it would train"]


def overlay_configs(
    kind: OverlayKind,
    overlay: Mapping[str, object],
    base: Mapping[str, object],
    phase_template: Mapping[str, object],
    phase_path: str,
) -> OverlayConfigs:
    """ValueError for an overlay that changes anything but its kind's settings, still holds a placeholder, or whose
    loop config would not be budgeted by generated tokens."""
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
    return OverlayConfigs(loop, merged(phase_template, overlay.get("phase", {})))
