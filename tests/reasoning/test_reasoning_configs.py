import tomllib
from pathlib import Path

import pytest

from lean_search.reasoning.config import load_reasoning_run_config
from lean_search.reasoning.dataset import ReasoningDataConfig
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object

CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "reasoning"


@pytest.mark.parametrize(
    "path",
    [*CONFIG_DIRECTORY.glob("phase5_sample_*.toml"), *CONFIG_DIRECTORY.glob("phase5_pilot_*.toml")],
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
