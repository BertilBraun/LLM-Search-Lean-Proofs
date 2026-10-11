"""Run configuration loaded from TOML (experiments/configs/) into dataclasses."""

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.search.expanders import AutomationConfig, AutomationExpander, Expander
from lean_search.search.priority import PriorityConfig
from lean_search.search.records import from_json_object
from lean_search.search.search import SearchConfig


class ExpanderKind(StrEnum):
    AUTOMATION = "automation"


@dataclass(frozen=True)
class ExpanderConfig:
    kind: ExpanderKind = ExpanderKind.AUTOMATION


@dataclass(frozen=True)
class LeanConfig:
    pool_size: int = 32
    concurrency: int = 32
    restart_fraction: float = 0.5


@dataclass(frozen=True)
class RunConfig:
    lean: LeanConfig = field(default_factory=LeanConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    expander: ExpanderConfig = field(default_factory=ExpanderConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    priority: PriorityConfig = field(default_factory=PriorityConfig)


def parse_run_config(text: str) -> RunConfig:
    config = from_json_object(RunConfig, tomllib.loads(text))
    if not 0 < config.lean.concurrency <= config.lean.pool_size:
        raise ValueError("lean.concurrency must be between 1 and lean.pool_size: each search holds one process.")
    if config.search.max_expansions < 1 or config.search.max_depth < 1 or config.search.max_wall_seconds <= 0:
        raise ValueError("search budgets must be positive.")
    return config


def load_run_config(path: Path) -> RunConfig:
    return parse_run_config(path.read_text(encoding="utf-8"))


def build_expander(config: RunConfig) -> Expander:
    match config.expander.kind:
        case ExpanderKind.AUTOMATION:
            return AutomationExpander(config.automation)
