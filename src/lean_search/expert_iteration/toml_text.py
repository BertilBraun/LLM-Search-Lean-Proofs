"""Writes the TOML the loop generates from templates (scalars, arrays, nested tables; tables inside an array inline)."""

import json
from collections.abc import Mapping


def toml_value(value: object) -> str:
    match value:
        case bool():
            return "true" if value else "false"
        case int() | float():
            return repr(value)
        case str():
            # A JSON string is a valid TOML basic string.
            return json.dumps(value, ensure_ascii=False)
        case list() | tuple():
            return "[" + ", ".join(toml_value(element) for element in value) + "]"
        case Mapping():
            return "{" + ", ".join(f"{key} = {toml_value(element)}" for key, element in value.items()) + "}"
        case _:
            raise ValueError(f"Not a TOML value: {value!r}")


def toml_text(table: Mapping[str, object], prefix: str = "") -> str:
    """Keys first, then each sub-table under its dotted name, the way tomllib reads it back."""
    lines = [f"{key} = {toml_value(value)}" for key, value in table.items() if not isinstance(value, Mapping)]
    sections = [
        f"\n[{prefix}{key}]\n" + toml_text(value, f"{prefix}{key}.")
        for key, value in table.items()
        if isinstance(value, Mapping)
    ]
    return "\n".join(lines) + ("\n" if lines else "") + "".join(sections)
