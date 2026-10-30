import dataclasses
from pathlib import Path

import pytest
from loop_fakes import LOOP_TOML

from lean_search.policy.config import FeedbackConfig
from lean_search.rl.budget_signals import arm_outcomes
from lean_search.rl.loop_config import parse_loop_config
from lean_search.rl.search_models import options_run_config
from lean_search.rl.search_options import (
    CONTROL_ARM,
    OptionsArmConfig,
    SearchOptions,
    search_arm,
    with_search_options,
    without_search_options,
)
from lean_search.rl.tree_store import TreeEntry
from lean_search.rl.tree_summary import TreeSummary
from lean_search.search import RunConfig, load_run_config

REPOSITORY = Path(__file__).resolve().parents[2]
FEEDBACK = SearchOptions(feedback=FeedbackConfig(enabled=True))
ARM = OptionsArmConfig("feedback", FEEDBACK)


def template() -> RunConfig:
    return load_run_config(REPOSITORY / "experiments" / "configs" / "grpo" / "search" / "visible_student_v2.toml")


def test_evaluation_template_turns_every_option_off() -> None:
    enabled = with_search_options(template(), dataclasses.replace(FEEDBACK, failed_automation_in_prompt=True))
    assert without_search_options(enabled).policy == without_search_options(template()).policy


def test_failed_automation_in_the_prompt_turns_overlap_off() -> None:
    options = SearchOptions(failed_automation_in_prompt=True)
    assert options_run_config(template(), options).expander.overlap is False


def test_options_arm_config_is_the_template_with_its_options() -> None:
    assert options_run_config(template(), FEEDBACK).policy.feedback.enabled


def test_statements_split_into_both_arms() -> None:
    assert {search_arm(ARM, f"statement_{index}") for index in range(64)} == {CONTROL_ARM, "feedback"}


def test_a_statement_keeps_its_arm() -> None:
    assert search_arm(ARM, "mathd_algebra_10") == search_arm(ARM, "mathd_algebra_10")


def test_without_the_a_b_a_statement_has_no_arm() -> None:
    assert search_arm(OptionsArmConfig(), "mathd_algebra_10") == ""


def test_options_arm_may_not_be_called_control() -> None:
    with pytest.raises(ValueError):
        parse_loop_config(LOOP_TOML + '\n[sampling.options_arm]\nname = "control"\n')


def test_options_arm_is_read_from_the_loop_config() -> None:
    text = LOOP_TOML.replace("status_seconds = 0.01\n", 'status_seconds = 0.01\n[sampling.options_arm]\nname = "fb"\n')
    assert parse_loop_config(text).sampling.options_arm.name == "fb"


def arm_entry(arm: str, proved: bool, groups: int, tokens: int) -> TreeEntry:
    summary = TreeSummary(32, 1 if proved else None, None, groups, arm=arm, generated_tokens=tokens)
    return TreeEntry(0, "p", 1, "f", proved, int(proved), 1, 0, None, 0.0, 0.0, summary)


def test_arm_outcomes_sum_each_arm_s_trees() -> None:
    entries = [arm_entry("control", True, 2, 1000), arm_entry("fb", False, 0, 3000), arm_entry("fb", True, 1, 1000)]
    outcomes = arm_outcomes(entries)
    assert (outcomes["fb"].trees, outcomes["fb"].solved, outcomes["fb"].solved_per_million_tokens) == (2, 1, 250.0)


def test_without_the_a_b_there_are_no_arm_outcomes() -> None:
    assert arm_outcomes([arm_entry("", True, 1, 100)]) == {}
