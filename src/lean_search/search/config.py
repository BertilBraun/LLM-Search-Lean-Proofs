"""Run configuration loaded from TOML (experiments/configs/) into dataclasses."""

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.policy.config import PolicyConfig, policy_config_problem
from lean_search.search.expanders import AutomationConfig, AutomationExpander, CompositeExpander, Expander
from lean_search.search.priority import PriorityConfig, PriorityKind
from lean_search.search.records import from_json_object
from lean_search.search.search import SearchConfig
from lean_search.value.config import ValueConfig


class ExpanderKind(StrEnum):
    AUTOMATION = "automation"
    POLICY = "policy"
    AUTOMATION_THEN_POLICY = "automation_then_policy"

    @property
    def uses_policy(self) -> bool:
        return self != ExpanderKind.AUTOMATION


@dataclass(frozen=True)
class ExpanderConfig:
    kind: ExpanderKind = ExpanderKind.AUTOMATION
    # automation_then_policy: send the policy request when the expansion starts, while the sweep runs.
    overlap: bool = False


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
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    value: ValueConfig = field(default_factory=ValueConfig)


def parse_run_config(text: str) -> RunConfig:
    config = from_json_object(RunConfig, tomllib.loads(text))
    if not 0 < config.lean.concurrency <= config.lean.pool_size:
        raise ValueError("lean.concurrency must be between 1 and lean.pool_size: each search holds one process.")
    if config.search.max_expansions < 1 or config.search.max_depth < 1 or config.search.max_wall_seconds <= 0:
        raise ValueError("search budgets must be positive.")
    exploration = config.search.exploration
    if not 0 <= exploration.epsilon <= 1 or exploration.top_k < 1:
        raise ValueError("search.exploration needs epsilon in [0, 1] and a positive top_k.")
    if config.search.harvest.max_expansions < 0:
        raise ValueError("search.harvest.max_expansions must not be negative.")
    if config.expander.kind.uses_policy and not (config.policy.model and config.policy.tokenizer):
        raise ValueError("A policy expander needs policy.model and policy.tokenizer.")
    if config.policy.sample_count < 1 or not config.policy.server_urls:
        raise ValueError("policy.sample_count must be positive and policy.server_urls not empty.")
    if (problem := policy_config_problem(config.policy)) is not None:
        raise ValueError(problem)
    if config.value.model and not (config.priority.kind == PriorityKind.A_STAR and config.value.tokenizer):
        raise ValueError('A value model needs priority.kind = "a_star" and value.tokenizer.')
    if not config.value.server_urls or config.value.top_k < 1:
        raise ValueError("value.server_urls must not be empty and value.top_k must be positive.")
    return config


def load_run_config(path: Path) -> RunConfig:
    return parse_run_config(path.read_text(encoding="utf-8"))


def build_expander(config: RunConfig, policy: Expander | None = None) -> Expander:
    """`policy` is the opened policy expander (lean_search.policy.expander) for the kinds that use one."""
    match config.expander.kind:
        case ExpanderKind.AUTOMATION:
            return AutomationExpander(config.automation)
        case ExpanderKind.POLICY:
            assert policy is not None
            return policy
        case ExpanderKind.AUTOMATION_THEN_POLICY:
            assert policy is not None
            return CompositeExpander([AutomationExpander(config.automation), policy], config.expander.overlap)
