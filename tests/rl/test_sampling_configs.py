"""The search efficiency switches belong to the arms' training sampling only: the sampling modes name copies of the
student search configs with the switches on; probe runs and held-out evaluations keep the plain files and turn the
switches off."""

import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.lean.nlinarith import NlinarithVariant
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_models import evaluation_run_config
from lean_search.rl.study_configs import sampling_record, sampling_refusal
from lean_search.search import RunConfig, load_run_config
from lean_search.search.search import TimeoutSkipConfig

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIGS = REPOSITORY / "experiments/configs/grpo"
MODES = ("visible", "no_reasoning")
STUDENTS = {"visible": "visible_student_v2", "no_reasoning": "no_reasoning_student_v2"}


def mode_sampling(mode: str) -> dict:
    return tomllib.loads((CONFIGS / f"followup/modes/{mode}.toml").read_text(encoding="utf-8"))["sampling"]


def mode_search_config(mode: str) -> RunConfig:
    return load_run_config(REPOSITORY / mode_sampling(mode)["search_config"])


def without_switches(config: RunConfig) -> RunConfig:
    search = dataclasses.replace(config.search, result_cache=None, timeout_skip=None, nlinarith_variant=None)
    return dataclasses.replace(config, search=search, lean=dataclasses.replace(config.lean, spare_processes=None))


@pytest.mark.parametrize("mode", MODES)
def test_a_sampling_mode_searches_with_the_result_cache(mode: str) -> None:
    assert mode_search_config(mode).search.result_cache is True


@pytest.mark.parametrize("mode", MODES)
def test_a_sampling_mode_searches_with_the_timeout_skip_at_two_stops(mode: str) -> None:
    assert mode_search_config(mode).search.timeout_skip == TimeoutSkipConfig(True, 2)


@pytest.mark.parametrize("mode", MODES)
def test_a_sampling_mode_runs_nlinarith_as_the_degree_bounded_variant(mode: str) -> None:
    assert mode_search_config(mode).search.nlinarith_variant == NlinarithVariant.DEGREE


@pytest.mark.parametrize("mode", MODES)
def test_a_sampling_mode_keeps_eight_spare_processes(mode: str) -> None:
    assert mode_search_config(mode).lean.spare_processes == 8


@pytest.mark.parametrize("mode", MODES)
def test_a_sampling_config_is_its_student_config_but_for_the_switches(mode: str) -> None:
    student = load_run_config(CONFIGS / f"search/{STUDENTS[mode]}.toml")
    assert without_switches(mode_search_config(mode)) == student


def test_the_probe_evaluation_searches_without_the_switches() -> None:
    probe = tomllib.loads((CONFIGS / "followup/probe_evaluation.toml").read_text(encoding="utf-8"))
    config = load_run_config(REPOSITORY / probe["search_config"])
    assert without_switches(config) == config


@pytest.mark.parametrize("mode", MODES)
def test_an_evaluation_from_a_sampling_config_turns_the_switches_off(mode: str) -> None:
    config = evaluation_run_config(mode_search_config(mode), EvaluationTarget(16, 3600.0, 56))
    assert without_switches(config) == config


@pytest.mark.parametrize("mode", MODES)
def test_an_arm_in_the_shared_runs_mode_is_accepted(mode: str) -> None:
    record = sampling_record(mode_sampling(mode), REPOSITORY)
    assert sampling_refusal(record, record) is None


def test_an_arm_with_the_plain_student_config_is_refused_against_a_shared_run_with_the_switches() -> None:
    shared = sampling_record(mode_sampling("visible"), REPOSITORY)
    plain = dict(mode_sampling("visible"), search_config="experiments/configs/grpo/search/visible_student_v2.toml")
    assert sampling_refusal(sampling_record(plain, REPOSITORY), shared) is not None
