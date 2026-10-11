from pathlib import Path

import pytest

from lean_search.policy import PolicyClient

LEAN_PROMPT = "theorem add_comm_example (a b : Nat) : a + b = b + a := by\n  "


async def test_zero_initialized_adapter_matches_the_base_model(
    policy_client: PolicyClient, served_model_repository: str, tmp_path: Path
) -> None:
    adapters = pytest.importorskip("lean_search.policy.adapters")
    adapters.create_zero_adapter(served_model_repository, tmp_path / "zero-adapter", rank=8)
    await policy_client.load_adapter("zero-adapter-test", str(tmp_path / "zero-adapter"))
    try:
        base = await policy_client.generate(LEAN_PROMPT, sample_count=1, max_tokens=16, temperature=0.0)
        adapted = await policy_client.generate(
            LEAN_PROMPT, sample_count=1, max_tokens=16, temperature=0.0, adapter="zero-adapter-test"
        )
    finally:
        await policy_client.unload_adapter("zero-adapter-test")
    assert adapted.samples[0].text == base.samples[0].text
