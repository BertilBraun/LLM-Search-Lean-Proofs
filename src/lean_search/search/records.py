"""JSON records: typed loading of dataclasses from JSON/TOML data and the per-theorem search-tree record."""

import dataclasses
import gzip
import json
import types
import typing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from lean_search.search.search import SearchResult
from lean_search.search.tree import Edge, NodeStatus, SearchTree, StepSource


@dataclass(frozen=True)
class NodeRecord:
    node_id: int
    parent_id: int | None
    edge_id: int | None
    step: str | None
    source: StepSource | None
    log_probability: float | None
    depth: int
    goals: tuple[str, ...]
    status: NodeStatus
    priority: float | None
    value_estimate: float | None
    child_ids: tuple[int, ...]
    created_seconds: float
    step_lean_seconds: float
    expansion_index: int | None
    expanded_seconds: float | None
    expansion_wall_seconds: float | None
    expansion_lean_seconds: float | None
    verification_problems: tuple[str, ...]
    # Absent from records written before generation cost was charged per batch.
    expansion_prompt_tokens: int | None = None
    expansion_generated_tokens: int | None = None


@dataclass(frozen=True)
class TreeRecord:
    problem_name: str
    statement: str
    result: SearchResult
    nodes: tuple[NodeRecord, ...]
    edges: tuple[Edge, ...]


def tree_record(tree: SearchTree, statement: str, result: SearchResult) -> TreeRecord:
    nodes = tuple(
        NodeRecord(
            node_id=node.node_id,
            parent_id=node.parent_id,
            edge_id=node.edge_id,
            step=node.step,
            source=node.source,
            log_probability=node.log_probability,
            depth=node.depth,
            goals=node.goals,
            status=node.status,
            priority=node.priority,
            value_estimate=node.value_estimate,
            child_ids=tuple(node.child_ids),
            created_seconds=node.created_seconds,
            step_lean_seconds=node.step_lean_seconds,
            expansion_index=node.expansion_index,
            expanded_seconds=node.expanded_seconds,
            expansion_wall_seconds=node.expansion_wall_seconds,
            expansion_lean_seconds=node.expansion_lean_seconds,
            verification_problems=node.verification_problems,
            expansion_prompt_tokens=node.expansion_prompt_tokens,
            expansion_generated_tokens=node.expansion_generated_tokens,
        )
        for node in tree.nodes
    )
    return TreeRecord(tree.problem_name, statement, result, nodes, tuple(tree.edges))


def to_json(value: object) -> str:
    assert dataclasses.is_dataclass(value) and not isinstance(value, type)
    return json.dumps(dataclasses.asdict(value), ensure_ascii=False)


def write_tree(path: Path, record: TreeRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write(to_json(record))


def read_tree(path: Path) -> TreeRecord:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return from_json_object(TreeRecord, json.load(file))


def read_results(path: Path) -> list[SearchResult]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(SearchResult, json.loads(line)) for line in lines if line.strip()]


def from_json_object[T](target: type[T], data: object) -> T:
    """Builds a (nested) dataclass from parsed JSON or TOML; raises ValueError for anything that does not fit."""
    return typing.cast(T, _convert(target, data, target.__name__))


def _convert(type_hint: object, data: object, location: str) -> object:
    origin = typing.get_origin(type_hint)
    arguments = typing.get_args(type_hint)
    if origin is types.UnionType or origin is typing.Union:
        if data is None and type(None) in arguments:
            return None
        (inner,) = (argument for argument in arguments if argument is not type(None))
        return _convert(inner, data, location)
    if origin is tuple or origin is list:
        if not isinstance(data, list | tuple):
            raise ValueError(f"{location}: expected a list, got {data!r}")
        element_type = arguments[0]
        elements = [_convert(element_type, element, f"{location}[{index}]") for index, element in enumerate(data)]
        return tuple(elements) if origin is tuple else elements
    assert isinstance(type_hint, type), type_hint
    if dataclasses.is_dataclass(type_hint):
        return _convert_dataclass(type_hint, data, location)
    if issubclass(type_hint, Enum):
        try:
            return type_hint(data)
        except ValueError as error:
            raise ValueError(f"{location}: {error}") from error
    if type_hint is float and isinstance(data, int | float) and not isinstance(data, bool):
        return float(data)
    if type(data) is not type_hint:
        raise ValueError(f"{location}: expected {type_hint.__name__}, got {data!r}")
    return data


def _convert_dataclass(target: type, data: object, location: str) -> object:
    if not isinstance(data, dict):
        raise ValueError(f"{location}: expected a table, got {data!r}")
    fields = {field.name: field for field in dataclasses.fields(target)}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"{location}: unknown keys {unknown}")
    missing = sorted(
        name
        for name, field in fields.items()
        if name not in data and field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    )
    if missing:
        raise ValueError(f"{location}: missing keys {missing}")
    hints = typing.get_type_hints(target)
    return target(**{name: _convert(hints[name], value, f"{location}.{name}") for name, value in data.items()})
