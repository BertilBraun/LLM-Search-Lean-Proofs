"""A reasoning run's configuration, loaded from TOML (experiments/configs/reasoning/)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.policy.config import PolicyConfig, policy_config_problem
from lean_search.reasoning.dataset import SelectionConfig
from lean_search.reasoning.pipeline import ExecutionConfig, PipelineConfig
from lean_search.reasoning.reward import RewardConfig
from lean_search.reasoning.shortening import ShorteningConfig
from lean_search.reasoning.states import StateSelectionConfig
from lean_search.search.records import from_json_object
from lean_search.value.config import ValueConfig


@dataclass(frozen=True)
class ReasoningRunConfig:
    policy: PolicyConfig
    states: StateSelectionConfig = field(default_factory=StateSelectionConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    # Only for the run's statistics; the data set's own selection is in ReasoningDataConfig.
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    # The served value adapter, needed only with reward.value_progress.
    value: ValueConfig = field(default_factory=ValueConfig)
    # Compressing long successful reasoning (and rationalizing steps) for short-reasoning data.
    shortening: ShorteningConfig = field(default_factory=ShorteningConfig)


def parse_reasoning_run_config(text: str) -> ReasoningRunConfig:
    config = from_json_object(ReasoningRunConfig, tomllib.loads(text))
    if not (config.policy.model and config.policy.tokenizer):
        raise ValueError("A reasoning run needs policy.model and policy.tokenizer.")
    if (problem := policy_config_problem(config.policy)) is not None:
        raise ValueError(problem)
    if config.reward.value_progress and not (config.value.model and config.value.tokenizer):
        raise ValueError("reward.value_progress needs value.model and value.tokenizer.")
    return config


def load_reasoning_run_config(path: Path) -> ReasoningRunConfig:
    return parse_reasoning_run_config(path.read_text(encoding="utf-8"))
