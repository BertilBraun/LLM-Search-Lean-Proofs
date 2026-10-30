"""The served models behind the loop's and the evaluations' searches, and the run configs those searches use."""

import contextlib
import dataclasses
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from lean_search.expert_iteration.loop_config import ServingConfig
from lean_search.expert_iteration.loop_search import GatedExpander, GatedValueEstimator, PauseGate
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.policy.expander import PolicyStatistics, open_policy_expander
from lean_search.rl.loop_config import EvaluationTarget, SamplingConfig
from lean_search.rl.search_options import SearchOptions, with_search_options, without_search_options
from lean_search.search import (
    Expander,
    PriorityFunction,
    RunConfig,
    ValueEstimator,
    build_expander,
    build_priority_function,
)
from lean_search.search.config import parse_run_config
from lean_search.value.estimator import open_value_estimator


@dataclass(frozen=True)
class SearchModels:
    expander: Expander
    priority_function: PriorityFunction
    # None for an expander without the policy.
    policy_statistics: PolicyStatistics | None


def served_run_config(template: RunConfig, serving: ServingConfig) -> RunConfig:
    """The template on the merged policy and value servers; a template without a value model keeps none."""
    policy = dataclasses.replace(
        template.policy,
        model=serving.policy_model,
        adapter=None,
        server_urls=tuple(server.url for server in serving.policy_servers),
    )
    value = (
        dataclasses.replace(
            template.value,
            model=serving.value_model,
            adapter=None,
            server_urls=tuple(server.url for server in serving.value_servers),
        )
        if template.value.model
        else template.value
    )
    return dataclasses.replace(template, policy=policy, value=value)


def training_run_config(config: RunConfig, sampling: SamplingConfig) -> RunConfig:
    """The loop's own searches: the loop's expansion budget, one REPL per concurrent search."""
    search = dataclasses.replace(config.search, max_expansions=sampling.max_expansions)
    lean = dataclasses.replace(config.lean, pool_size=sampling.concurrency, concurrency=sampling.concurrency)
    return dataclasses.replace(config, search=search, lean=lean)


def evaluation_run_config(config: RunConfig, target: EvaluationTarget) -> RunConfig:
    """A fixed-target search: the target's budget and REPLs, no harvesting, no ε-exploration."""
    search = dataclasses.replace(
        config.search,
        max_expansions=target.max_expansions,
        max_wall_seconds=target.max_wall_seconds,
        harvest=dataclasses.replace(config.search.harvest, enabled=False),
        exploration=dataclasses.replace(config.search.exploration, enabled=False),
    )
    lean = dataclasses.replace(config.lean, pool_size=target.concurrency, concurrency=target.concurrency)
    return dataclasses.replace(config, search=search, lean=lean)


def without_none(value: object) -> object:
    match value:
        case Mapping():
            return {key: without_none(item) for key, item in value.items() if item is not None}
        case list() | tuple():
            return [without_none(item) for item in value]
        case _:
            return value


def run_config_text(config: RunConfig) -> str:
    """The config as TOML that load_run_config reads back (fields that are None take their default)."""
    table = without_none(dataclasses.asdict(config))
    assert isinstance(table, Mapping)
    return toml_text(table)


def options_run_config(template: RunConfig, options: SearchOptions) -> RunConfig:
    """The template with the options on (and every other off), validated like a config file."""
    return parse_run_config(run_config_text(with_search_options(without_search_options(template), options)))


@contextlib.asynccontextmanager
async def open_search_models(config: RunConfig, gate: PauseGate | None = None) -> AsyncIterator[SearchModels]:
    """The policy expander and the priority function; with a gate, their requests wait while it is paused."""
    async with contextlib.AsyncExitStack() as stack:
        policy: Expander | None = None
        statistics = None
        if config.expander.kind.uses_policy:
            opened = await stack.enter_async_context(open_policy_expander(config.policy, config.search.forbidden_steps))
            statistics = opened.statistics
            policy = opened if gate is None else GatedExpander(opened, gate)
        value_estimator: ValueEstimator | None = None
        if config.value.model:
            opened_value = await stack.enter_async_context(open_value_estimator(config.value))
            value_estimator = opened_value if gate is None else GatedValueEstimator(opened_value, gate)
        yield SearchModels(
            build_expander(config, policy), build_priority_function(config.priority, value_estimator), statistics
        )
