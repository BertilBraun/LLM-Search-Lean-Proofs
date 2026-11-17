"""Dataclass records as JSON-ready values. A field declared with `written_when_set` is left out while it holds its
default, so records of runs that do not use a newer feature stay as they were, readable by readers from before it."""

import copy
import dataclasses
from typing import Any

WRITTEN_WHEN_SET = "written_when_set"


def written_when_set(default: Any) -> Any:
    """A field with an immutable default that records write only when it differs from it."""
    return dataclasses.field(default=default, metadata={WRITTEN_WHEN_SET: True})


def record_dict(value: object) -> dict[str, Any]:
    """`dataclasses.asdict`, without the `written_when_set` fields at their defaults."""
    assert dataclasses.is_dataclass(value) and not isinstance(value, type)
    converted = _converted(value)
    assert isinstance(converted, dict)
    return converted


def _converted(value: object) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        result = {}
        for field in dataclasses.fields(value):
            item = getattr(value, field.name)
            if field.metadata.get(WRITTEN_WHEN_SET) and item == field.default:
                continue
            result[field.name] = _converted(item)
        return result
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return type(value)(*(_converted(item) for item in value))
    if isinstance(value, list | tuple):
        return type(value)(_converted(item) for item in value)
    if isinstance(value, dict):
        return type(value)((_converted(key), _converted(item)) for key, item in value.items())
    return copy.deepcopy(value)
