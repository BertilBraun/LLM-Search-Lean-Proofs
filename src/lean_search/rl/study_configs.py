"""The follow-up study's config files: placeholders and the arms.

A setting the study fills in later is a string starting with PLACEHOLDER where a number or a path belongs, so the
config does not load and a launcher names what is left to set. An arm (experiments/configs/grpo/followup/arms/) is a
thin file over base.toml and base.toml's phase template whose [loop] and [phase] tables change only `ARM_SETTINGS`;
experiments/followup_arm.py writes the two configs the loop reads.
"""

from collections.abc import Mapping
from dataclasses import dataclass

PLACEHOLDER = "PLACEHOLDER"
# An arm is base.toml and its phase template changed only here (DESIGN.md, "Arms": everything else identical).
ARM_SETTINGS = frozenset(
    {
        "loop.name",
        # A second seed (WP1's seed offset).
        "loop.training.seed_offset",
        "phase.policy.data.credit",
        "phase.policy.optimization.learning_rate",
    }
)


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
    """`base` with `overlay`'s values in place, table by table."""
    result = dict(base)
    for key, value in overlay.items():
        base_value = result.get(key)
        if isinstance(value, Mapping) and isinstance(base_value, Mapping):
            result[key] = merged(base_value, value)
        else:
            result[key] = value
    return result


@dataclass(frozen=True)
class ArmConfigs:
    # The loop config, its training.phase_config set to where the phase config goes, and that phase config.
    loop: dict[str, object]
    phase: dict[str, object]


def arm_configs(
    arm: Mapping[str, object], base: Mapping[str, object], phase_template: Mapping[str, object], phase_path: str
) -> ArmConfigs:
    """ValueError for an arm that changes anything but `ARM_SETTINGS` or still holds a placeholder."""
    unexpected = [key for key in leaf_keys(arm) if key not in ARM_SETTINGS]
    if unexpected:
        raise ValueError(f"An arm changes only {sorted(ARM_SETTINGS)}, not {unexpected}.")
    left = placeholders(arm)
    if left:
        raise ValueError(f"The arm still has placeholders at {left}.")
    loop = merged(base, arm.get("loop", {}))
    loop["training"] = {**loop["training"], "phase_config": phase_path}
    return ArmConfigs(loop, merged(phase_template, arm.get("phase", {})))
