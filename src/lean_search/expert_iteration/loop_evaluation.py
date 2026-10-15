"""The periodic miniF2F-valid evaluation of published versions at a reduced budget."""

import datetime
import json
import tomllib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.loop_config import EvaluationLoopConfig, ServingConfig, ThinkingConfig
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
    """The current version when due (0, the baseline, then every `every_versions`-th) and not evaluated yet."""
    if not versions:
        return None
    current = versions[-1]
    is_due = current.version % config.every_versions == 0
    return current if is_due and current.version not in evaluated else None


def evaluation_due(
    evaluations: Sequence[EvaluationRecord], current: datetime.datetime, config: EvaluationLoopConfig
) -> bool:
    """No evaluation yet, or the last one finished `every_hours` ago."""
    if not evaluations:
        return True
    finished = datetime.datetime.fromisoformat(evaluations[-1].finished_at)
    return (current - finished).total_seconds() >= config.every_hours * 3600


def evaluation_config_text(
    template: str, serving: ServingConfig, config: EvaluationLoopConfig, thinking: ThinkingConfig
) -> str:
    """The template on the merged servers, in the loop's thinking mode, at the evaluation's budget and concurrency."""
    table = tomllib.loads(template)
    table["lean"] = table.get("lean", {}) | {"pool_size": config.concurrency, "concurrency": config.concurrency}
    table["search"] = table.get("search", {}) | {"max_expansions": config.max_expansions}
    for section, model, servers in (
        ("policy", serving.policy_model, serving.policy_servers),
        ("value", serving.value_model, serving.value_servers),
    ):
        section_table = {key: value for key, value in table[section].items() if key != "adapter"}
        table[section] = section_table | {"model": model, "server_urls": [server.url for server in servers]}
    if thinking.enabled:
        table["policy"] |= {"max_tokens": thinking.max_tokens, **reasoning_settings(thinking)}
    return toml_text(table)


def reasoning_settings(thinking: ThinkingConfig) -> dict[str, object]:
    """The policy fields of the loop's reasoning mode: thinking, or a visible explanation with thinking off."""
    if thinking.visible:
        return {"thinking": False, "visible_reasoning": True, "few_shot": False, "thinking_instruction": ""}
    return {"thinking": True, "visible_reasoning": False, "thinking_instruction": thinking.instruction}


def read_evaluations(path: Path) -> list[EvaluationRecord]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(EvaluationRecord, json.loads(line)) for line in lines if line.strip()]


def append_evaluation(path: Path, record: EvaluationRecord) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(to_json(record) + "\n")
