import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from lean_search.policy.adapters import create_zero_adapter  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig, load_trainable_model  # noqa: E402

MODEL = "Qwen/Qwen3.5-0.8B"
ADAPTER_RANK = 8


@pytest.fixture(scope="module")
def continued_model(tmp_path_factory: pytest.TempPathFactory) -> torch.nn.Module:
    try:
        transformers.AutoConfig.from_pretrained(MODEL, local_files_only=True)
    except OSError:
        pytest.skip(f"{MODEL} is not in the Hugging Face cache")
    adapter_directory = tmp_path_factory.mktemp("adapter")
    create_zero_adapter(MODEL, adapter_directory, rank=ADAPTER_RANK)
    optimization = OptimizationConfig(gradient_checkpointing=False)
    module, _ = load_trainable_model(
        MODEL, optimization, LoraSettings(rank=64), torch.device("cpu"), initial_adapter=str(adapter_directory)
    )
    return module


def test_a_continued_adapter_trains_only_its_lora_weights(continued_model: torch.nn.Module) -> None:
    trainable = [name for name, parameter in continued_model.named_parameters() if parameter.requires_grad]
    assert trainable and all(".lora_" in name for name in trainable)


def test_a_continued_adapter_keeps_its_own_rank(continued_model: torch.nn.Module) -> None:
    assert continued_model.peft_config["default"].r == ADAPTER_RANK
