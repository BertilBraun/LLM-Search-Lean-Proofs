"""The periodic miniF2F-valid evaluation of published versions at a reduced budget."""

import json
import tomllib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.loop_config import EvaluationLoopConfig, ServingConfig
from lean_search.expert_iteration.serving import ModelVersion
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.search.records import from_json_object, to_json


@dataclass(frozen=True)
class EvaluationRecord:
    version: int
    run_name: str
    problems: int
    solved: int
    started_at: str
    finished_at: str


def due_version(
    versions: Sequence[ModelVersion], evaluated: Collection[int], config: EvaluationLoopConfig
) -> ModelVersion | None:
    """The current version when it is due (every `every_versions`-th) and not evaluated yet."""
    if not versions:
        return None
    current = versions[-1]
    is_due = current.version > 0 and current.version % config.every_versions == 0
    return current if is_due and current.version not in evaluated else None


def evaluation_config_text(template: str, serving: ServingConfig, config: EvaluationLoopConfig) -> str:
    """The template on the served adapters at the evaluation's budget and concurrency."""
    table = tomllib.loads(template)
    urls = [server.url for server in serving.servers]
    table["lean"] = table.get("lean", {}) | {"pool_size": config.concurrency, "concurrency": config.concurrency}
    table["search"] = table.get("search", {}) | {"max_expansions": config.max_expansions}
    for section, adapter in (("policy", serving.policy_adapter_name), ("value", serving.value_adapter_name)):
        table[section] = table[section] | {"model": serving.served_model, "adapter": adapter, "server_urls": urls}
    return toml_text(table)


def read_evaluations(path: Path) -> list[EvaluationRecord]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(EvaluationRecord, json.loads(line)) for line in lines if line.strip()]


def append_evaluation(path: Path, record: EvaluationRecord) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(to_json(record) + "\n")
