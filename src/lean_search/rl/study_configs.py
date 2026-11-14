"""Settings the follow-up study fills in later, marked in its config files: a string value starting with PLACEHOLDER
where a number or a path belongs, so the config does not load, and a launcher names what is left to set."""

from collections.abc import Mapping

PLACEHOLDER = "PLACEHOLDER"


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
