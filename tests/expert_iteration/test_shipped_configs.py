import dataclasses
import re
import tomllib
from pathlib import Path

import pytest

from lean_search.expert_iteration.config import (
    adapter_mismatches,
    load_pool_config,
    load_round_config,
    unserved_adapters,
)
from lean_search.expert_iteration.known_proofs import load_known_proof_pool_config
from lean_search.expert_iteration.loop_config import load_loop_config
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
CONFIG_DIRECTORY = REPOSITORY_DIRECTORY / "experiments" / "configs" / "expert_iteration"
ROUND_CONFIGS = sorted(path for path in CONFIG_DIRECTORY.glob("*.toml") if re.fullmatch(r"round_\d+\.toml", path.name))


def test_the_pool_config_loads() -> None:
    assert load_pool_config(CONFIG_DIRECTORY / "pool_v1.toml").sources


def test_the_prefilter_is_automation_only() -> None:
    config = load_pool_config(CONFIG_DIRECTORY / "pool_v1.toml")
    assert not load_run_config(REPOSITORY_DIRECTORY / config.prefilter_search).expander.kind.uses_policy


@pytest.mark.parametrize("path", ROUND_CONFIGS, ids=lambda path: path.stem)
def test_the_round_search_requests_the_served_adapters(path: Path) -> None:
    config = load_round_config(path)
    search = load_run_config(REPOSITORY_DIRECTORY / config.search_config)
    assert adapter_mismatches(search, config.policy, config.value) == []


@pytest.mark.parametrize("path", ROUND_CONFIGS, ids=lambda path: path.stem)
def test_the_round_evaluations_request_only_served_adapters(path: Path) -> None:
    config = load_round_config(path)
    served = (config.policy, config.value, config.next_policy, config.next_value)
    problems = [
        problem
        for evaluation in config.evaluations
        for problem in unserved_adapters(load_run_config(REPOSITORY_DIRECTORY / evaluation.config), served)
    ]
    assert problems == []


@pytest.mark.parametrize("path", ROUND_CONFIGS, ids=lambda path: path.stem)
def test_the_round_evaluations_cover_distinct_adapter_pairs(path: Path) -> None:
    config = load_round_config(path)
    pairs = [load_run_config(REPOSITORY_DIRECTORY / evaluation.config) for evaluation in config.evaluations]
    assert len({(run.policy.adapter, run.value.adapter) for run in pairs}) == len(pairs)


@pytest.mark.parametrize("path", ROUND_CONFIGS, ids=lambda path: path.stem)
def test_the_round_training_configs_parse(path: Path) -> None:
    pytest.importorskip("torch")
    from lean_search.training.dpo import DpoConfig
    from lean_search.training.sft import SftConfig
    from lean_search.value.training import ValueTrainingConfig

    config = load_round_config(path)
    loaded = [
        from_json_object(target, tomllib.loads((REPOSITORY_DIRECTORY / relative).read_text(encoding="utf-8")))
        for target, relative in (
            (SftConfig, config.policy_sft_config),
            (DpoConfig, config.policy_dpo_config),
            (ValueTrainingConfig, config.value_config),
        )
    ]
    assert [type(training) for training in loaded] == [SftConfig, DpoConfig, ValueTrainingConfig]


def test_the_loop_config_loads() -> None:
    assert load_loop_config(CONFIG_DIRECTORY / "loop.toml").search.scheduler.stages


def test_the_loop_search_and_evaluation_templates_load() -> None:
    config = load_loop_config(CONFIG_DIRECTORY / "loop.toml")
    paths = (config.search.search_config, config.evaluation.config)
    templates = [load_run_config(REPOSITORY_DIRECTORY / path) for path in paths]
    assert all(template.value.model for template in templates)


def test_the_loop_training_templates_parse_once_filled() -> None:
    pytest.importorskip("torch")
    from lean_search.training.dpo import DpoConfig
    from lean_search.value.training import ValueTrainingConfig

    training = load_loop_config(CONFIG_DIRECTORY / "loop.toml").training
    value_continues = "initial_adapter" in {field.name for field in dataclasses.fields(ValueTrainingConfig)}
    filled = []
    for target, stage, takes_adapter in (
        (DpoConfig, training.policy, True),
        (ValueTrainingConfig, training.value, value_continues),
    ):
        table = tomllib.loads((REPOSITORY_DIRECTORY / stage.config).read_text(encoding="utf-8")) | {"data": "d"}
        if takes_adapter:
            table["initial_adapter"] = "/adapter"
        filled.append(from_json_object(target, table))
    assert [type(config) for config in filled] == [DpoConfig, ValueTrainingConfig]


def test_the_loop_pool_config_loads() -> None:
    assert load_pool_config(CONFIG_DIRECTORY / "pool_v2.toml").sources


def test_the_known_proof_pool_config_loads() -> None:
    config = load_known_proof_pool_config(CONFIG_DIRECTORY / "pool_v3.toml")
    assert [corpus.name for corpus in config.corpora if not corpus.pooled] == ["stp_conjectures"]
