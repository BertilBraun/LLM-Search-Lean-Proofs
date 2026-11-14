import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.loop_config import EvaluationTarget, load_loop_config
from lean_search.rl.probe_evaluation import (
    NO_VALUE_VERSION,
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    default_value_version,
    merged_weights_directory,
    probe_run_config,
    resolve_value_adapter,
    run_directory,
    run_record,
)
from lean_search.search import PriorityKind, load_run_config
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_DIRECTORY / "experiments/configs/grpo/followup/probe_evaluation.toml"
CONFIG = from_json_object(ProbeEvaluationConfig, tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
LOOP = load_loop_config(REPOSITORY_DIRECTORY / CONFIG.loop_config)
TEMPLATE = load_run_config(REPOSITORY_DIRECTORY / CONFIG.search_config)
TARGET = EvaluationTarget(16, 7200.0, 32)
CHECKPOINT = ProbeCheckpoint("/policy", "", 4, NO_VALUE_VERSION)


@pytest.mark.parametrize(("value", "adapter"), [("none", ""), ("v0", "/v0"), ("/value/adapter", "/value/adapter")])
def test_the_value_choice_names_its_adapter(value: str, adapter: str) -> None:
    assert resolve_value_adapter(value, "/v0") == adapter


@pytest.mark.parametrize(("value", "version"), [("none", NO_VALUE_VERSION), ("v0", 0), ("/value/adapter", None)])
def test_the_value_choice_has_a_default_label_unless_given_by_path(value: str, version: int | None) -> None:
    assert default_value_version(value) == version


def test_without_a_value_adapter_the_search_has_no_value_model() -> None:
    assert probe_run_config(TEMPLATE, LOOP.serving, TARGET, "").value.model == ""


def test_without_a_value_adapter_the_search_takes_the_value_free_priority() -> None:
    priority = probe_run_config(TEMPLATE, LOOP.serving, TARGET, "").priority
    assert priority == dataclasses.replace(TEMPLATE.priority, kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY)


def test_with_a_value_adapter_the_search_asks_the_value_servers() -> None:
    value = probe_run_config(TEMPLATE, LOOP.serving, TARGET, "/v0").value
    assert value.server_urls == tuple(server.url for server in LOOP.serving.value_servers)


def test_with_a_value_adapter_the_search_keeps_the_templates_priority() -> None:
    assert probe_run_config(TEMPLATE, LOOP.serving, TARGET, "/v0").priority == TEMPLATE.priority


def test_the_probe_searches_at_its_budget_wall_cap_and_concurrency() -> None:
    config = probe_run_config(TEMPLATE, LOOP.serving, TARGET, "/v0")
    assert (config.search.max_expansions, config.search.max_wall_seconds, config.lean.concurrency) == (16, 7200.0, 32)


def test_the_probe_searches_without_harvesting_or_exploration() -> None:
    search = probe_run_config(TEMPLATE, LOOP.serving, TARGET, "/v0").search
    assert (search.harvest.enabled, search.exploration.enabled) == (False, False)


def test_a_run_lies_where_the_probe_rating_looks(tmp_path: Path) -> None:
    assert run_directory(tmp_path, "arm_a_phase_08").name.startswith("probe_")


def test_policy_and_value_merges_of_one_adapter_are_apart(tmp_path: Path) -> None:
    assert merged_weights_directory(tmp_path, "/a", "policy") != merged_weights_directory(tmp_path, "/a", "value")


def summary(problems: int, stops: int) -> EvaluationSummary:
    return EvaluationSummary(
        EvaluationKind.PROBE, "probe_x", 4, -1, problems, 0, (), 16, 0, 0, 0.0, 0.0, "", "", 0, 0, stops
    )


@pytest.mark.parametrize(("stops", "accepted"), [(100, True), (101, False)])
def test_a_run_above_the_wall_clock_stop_share_is_rejected(stops: int, accepted: bool) -> None:
    assert run_record(CHECKPOINT, "search.toml", summary(2000, stops), 0.05).accepted == accepted


def test_the_record_gives_the_share_of_wall_clock_stops() -> None:
    assert run_record(CHECKPOINT, "search.toml", summary(2000, 50), 0.05).wall_clock_stop_share == 0.025


def test_the_shipped_probe_evaluation_raises_the_wall_cap_to_two_hours() -> None:
    assert (CONFIG.probe.max_expansions, CONFIG.probe.max_wall_seconds) == (16, 7200.0)
