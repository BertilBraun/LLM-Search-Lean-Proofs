"""The search efficiency switches at the config level: how a TOML turns them on, what load refuses, and that a config
without them keeps the digest and the records it had before they existed."""

import json
from pathlib import Path

import pytest

from lean_search.rl.probe_evaluation import run_config_sha256
from lean_search.rl.probe_run_list import planned_run_config_sha256, read_run_list
from lean_search.rl.search_models import run_config_text
from lean_search.search import Accounting, Edge, EdgeOutcome, StepSource, StepStatistics
from lean_search.search.config import parse_run_config
from lean_search.search.records import to_json
from lean_search.search.search import TimeoutSkipConfig

REPOSITORY = Path(__file__).resolve().parents[2]
# What runs 1, 2 and 9 of step 1 recorded on the node, and what master gave at 33c96ea.
STEP1_RUN_CONFIG_SHA256 = "eee4c06bd7274b4eee534f6ae7dd0ad7a2e018c19c3f92ca8e7f09052c3cacbb"
SWITCHES_ON = """
[search]
result_cache = true
[search.timeout_skip]
enabled = true
max_wall_clock_timeouts = 2
[lean]
spare_processes = 8
"""


def step1_run(name: str) -> object:
    runs = read_run_list(REPOSITORY / "experiments/configs/grpo/followup/step1/runs_order_check.toml").runs
    return next(run for run in runs if run.name == name)


def test_the_step1_probe_config_keeps_its_digest() -> None:
    run = step1_run("step1_run9_v0_value_v0_ordered")
    assert planned_run_config_sha256(run, REPOSITORY) == STEP1_RUN_CONFIG_SHA256


def test_a_toml_turns_the_result_cache_on() -> None:
    assert parse_run_config(SWITCHES_ON).search.result_cache is True


def test_a_toml_turns_the_timeout_skip_on() -> None:
    assert parse_run_config(SWITCHES_ON).search.timeout_skip == TimeoutSkipConfig(True, 2)


def test_a_toml_asks_for_spare_processes() -> None:
    assert parse_run_config(SWITCHES_ON).lean.spare_processes == 8


def test_a_config_without_the_switches_writes_none_of_them() -> None:
    text = run_config_text(parse_run_config(""))
    assert [key for key in ("result_cache", "timeout_skip", "spare_processes") if key in text] == []


def test_spare_processes_leave_the_digest_unchanged() -> None:
    assert run_config_sha256(parse_run_config("[lean]\nspare_processes = 8")) == run_config_sha256(parse_run_config(""))


@pytest.mark.parametrize("text", ["[search]\nresult_cache = true", "[search.timeout_skip]\nenabled = true"])
def test_switches_that_change_outcomes_change_the_digest(text: str) -> None:
    assert run_config_sha256(parse_run_config(text)) != run_config_sha256(parse_run_config(""))


@pytest.mark.parametrize(
    "text", ["[lean]\nspare_processes = -1", "[search.timeout_skip]\nenabled = true\nmax_wall_clock_timeouts = 0"]
)
def test_invalid_switch_settings_are_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(text)


def edge(cached_tactics: int) -> Edge:
    return Edge(
        0,
        0,
        0,
        "simp",
        StepSource.AUTOMATION,
        None,
        0,
        0,
        EdgeOutcome.FAILED,
        None,
        0,
        1,
        None,
        0.1,
        None,
        cached_tactics=cached_tactics,
    )


def test_an_edge_without_cache_hits_writes_the_keys_it_had_before() -> None:
    assert "cached_tactics" not in json.loads(to_json(edge(0)))


def test_an_edge_with_cache_hits_writes_them() -> None:
    assert json.loads(to_json(edge(2)))["cached_tactics"] == 2


def test_accounting_without_the_switches_writes_the_keys_it_had_before() -> None:
    written = set(json.loads(to_json(Accounting())))
    assert written & {"cached_tactics", "cache_saved_seconds", "skipped_timeouts"} == set()


def test_step_statistics_without_skips_write_the_keys_they_had_before() -> None:
    assert "skipped_timeouts" not in json.loads(to_json(StepStatistics("<policy>")))
