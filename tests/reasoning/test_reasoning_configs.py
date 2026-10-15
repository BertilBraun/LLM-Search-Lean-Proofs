import tomllib
from pathlib import Path

import pytest

from lean_search.policy.prompts import BRIEF_THINKING_INSTRUCTION
from lean_search.reasoning.config import load_reasoning_run_config
from lean_search.reasoning.dataset import ReasoningDataConfig
from lean_search.reasoning.shortening import ShorteningConfig
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object

CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "reasoning"


@pytest.mark.parametrize(
    "path",
    [
        *CONFIG_DIRECTORY.glob("phase5_bootstrap_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_pilot_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_eval_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_compare_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_size_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_teacher_*.toml"),
        *CONFIG_DIRECTORY.glob("phase5_visible_*.toml"),
    ],
    ids=lambda path: path.stem,
)
def test_sampling_configs_load(path: Path) -> None:
    assert load_reasoning_run_config(path).policy.model


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase5_data_*.toml")), ids=lambda path: path.stem)
def test_data_configs_load(path: Path) -> None:
    assert from_json_object(ReasoningDataConfig, tomllib.loads(path.read_text(encoding="utf-8"))).runs


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase5_search_*.toml")), ids=lambda path: path.stem)
def test_search_configs_load(path: Path) -> None:
    assert load_run_config(path).search.max_generated_tokens


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase5_sft_*.toml")), ids=lambda path: path.stem)
def test_sft_configs_continue_an_adapter(path: Path) -> None:
    pytest.importorskip("torch")
    from lean_search.training.sft import SftConfig

    assert from_json_object(SftConfig, tomllib.loads(path.read_text(encoding="utf-8"))).initial_adapter


@pytest.mark.parametrize(
    "path",
    [
        *CONFIG_DIRECTORY.glob("phase5_pilot_*_brief.toml"),
        *CONFIG_DIRECTORY.glob("phase5_size_*_bounded.toml"),
        *CONFIG_DIRECTORY.glob("phase5_teacher_*.toml"),
    ],
    ids=lambda path: path.stem,
)
def test_brief_arms_use_the_shared_instruction(path: Path) -> None:
    assert load_reasoning_run_config(path).policy.thinking_instruction == BRIEF_THINKING_INSTRUCTION


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase5_shortening_*.toml")), ids=lambda path: path.stem)
def test_shortening_configs_load(path: Path) -> None:
    assert from_json_object(ShorteningConfig, tomllib.loads(path.read_text(encoding="utf-8"))).rewrite.model


def data_config(name: str) -> ReasoningDataConfig:
    return from_json_object(ReasoningDataConfig, tomllib.loads((CONFIG_DIRECTORY / name).read_text("utf-8")))


@pytest.mark.parametrize(
    ("run_name", "data_name"),
    [("phase5_bootstrap_r1", "phase5_data_bootstrap_r1"), ("phase5_teacher_9b", "phase5_data_teacher_9b")],
)
def test_the_data_selection_matches_its_sampling_run(run_name: str, data_name: str) -> None:
    run = load_reasoning_run_config(CONFIG_DIRECTORY / f"{run_name}.toml")
    data = data_config(f"{data_name}.toml")
    assert (data.selection, data.max_kept_reasoning_tokens) == (
        run.selection,
        run.shortening.max_kept_reasoning_tokens,
    )


def test_the_student_data_drops_the_teacher_instruction() -> None:
    assert data_config("phase5_data_teacher_9b.toml").thinking_instruction == ""


def test_the_light_data_keeps_what_the_light_shortening_leaves_uncompressed() -> None:
    shortening = from_json_object(
        ShorteningConfig, tomllib.loads((CONFIG_DIRECTORY / "phase5_shortening_9b_light.toml").read_text("utf-8"))
    )
    data = data_config("phase5_data_teacher_9b_light.toml")
    assert (data.shortening, data.max_kept_reasoning_tokens) == ("9b_light", shortening.max_kept_reasoning_tokens)


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase5_expansions_*.toml")), ids=lambda path: path.stem)
def test_equal_expansion_configs_have_no_token_cap(path: Path) -> None:
    search = load_run_config(path).search
    assert (search.max_expansions, search.max_generated_tokens) == (64, None)


def test_the_equal_expansion_thinking_arm_forces_answers() -> None:
    policy = load_run_config(CONFIG_DIRECTORY / "phase5_expansions_student_4b_light_thinking.toml").policy
    assert (policy.thinking, policy.force_answer_on_truncation, policy.sample_count) == (True, True, 16)


@pytest.mark.parametrize(
    "path", sorted(CONFIG_DIRECTORY.glob("phase5_visible_probe_*.toml")), ids=lambda path: path.stem
)
def test_visible_probes_reason_visibly(path: Path) -> None:
    policy = load_reasoning_run_config(path).policy
    assert (policy.visible_reasoning, policy.thinking, policy.max_tokens) == (True, False, 1024)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("phase5_retention_visible_student_v2.toml", "qwen3.5-4b-visible-student-v2"),
        ("phase5_retention_visible_student_v2_nothinking.toml", "qwen3.5-4b-visible-student-v2-visible"),
    ],
)
def test_the_student_retention_configs_name_one_model(name: str, label: str) -> None:
    config = tomllib.loads((CONFIG_DIRECTORY / name).read_text("utf-8"))
    assert [model["label"] for model in config["models"]] == [label]
