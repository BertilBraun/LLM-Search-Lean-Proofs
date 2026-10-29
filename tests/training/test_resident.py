from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from lean_search.training.resident import HostWeights, park, unpark, write_host_weights  # noqa: E402

CPU = torch.device("cpu")


def frozen_linear() -> torch.nn.Module:
    """A frozen weight (parked in the shared file) and a trainable bias (parked privately), as a LoRA model has."""
    torch.manual_seed(0)
    module = torch.nn.Linear(4, 3).to(torch.bfloat16)
    module.weight.requires_grad_(False)
    module.register_buffer("scale", torch.arange(3, dtype=torch.float32))
    return module


def parked(tmp_path: Path) -> tuple[torch.nn.Module, HostWeights]:
    module = frozen_linear()
    write_host_weights(module, tmp_path / "weights.bin")
    host = HostWeights(tmp_path / "weights.bin")
    park(module, host)
    return module, host


def test_the_shared_file_holds_the_frozen_tensors_only(tmp_path: Path) -> None:
    _, host = parked(tmp_path)
    assert set(host.tensors) == {"weight", "scale"}


def test_a_parked_frozen_tensor_lives_in_the_shared_mapping(tmp_path: Path) -> None:
    module, host = parked(tmp_path)
    start = host.storage.data_ptr()
    assert start <= module.weight.data_ptr() < start + host.size


def test_two_mappings_of_the_file_share_their_memory(tmp_path: Path) -> None:
    _, host = parked(tmp_path)
    other = HostWeights(tmp_path / "weights.bin")
    host.tensors["scale"][0] = 7.0
    assert other.tensors["scale"][0].item() == 7.0


def test_the_parked_tensors_keep_their_values(tmp_path: Path) -> None:
    expected = frozen_linear().state_dict()
    module, _ = parked(tmp_path)
    assert all(torch.equal(tensor, expected[name]) for name, tensor in module.state_dict().items())


def test_an_in_place_change_after_unparking_leaves_the_parked_weights(tmp_path: Path) -> None:
    module, host = parked(tmp_path)
    expected = module.weight.clone()
    unpark(module, host, CPU)
    module.weight.data.add_(1.0)
    park(module, host)
    assert torch.equal(module.weight, expected)


def test_a_trainable_tensor_keeps_its_trained_values_through_parking(tmp_path: Path) -> None:
    module, host = parked(tmp_path)
    unpark(module, host, CPU)
    with torch.no_grad():
        module.bias.fill_(0.5)
    park(module, host)
    unpark(module, host, CPU)
    assert torch.equal(module.bias, torch.full((3,), 0.5, dtype=torch.bfloat16))


def test_parking_drops_the_gradients(tmp_path: Path) -> None:
    module, host = parked(tmp_path)
    unpark(module, host, CPU)
    module(torch.ones(1, 4, dtype=torch.bfloat16)).sum().backward()
    park(module, host)
    assert module.bias.grad is None
