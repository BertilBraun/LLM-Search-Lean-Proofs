import os
from collections.abc import AsyncIterator
from typing import NamedTuple

import httpx
import pytest

from lean_search.policy import PolicyClient

POLICY_URL = os.environ.get("LEAN_SEARCH_POLICY_URL", "http://127.0.0.1:8000/v1")


class ServedModel(NamedTuple):
    name: str
    repository: str


def find_served_base_model() -> ServedModel | None:
    try:
        response = httpx.get(f"{POLICY_URL}/models", timeout=5.0)
    except httpx.TransportError:
        return None
    base_models = [model for model in response.json()["data"] if model["parent"] is None]
    return ServedModel(name=base_models[0]["id"], repository=base_models[0]["root"])


@pytest.fixture(scope="session")
def served_model() -> ServedModel:
    model = find_served_base_model()
    if model is None:
        pytest.skip(f"no vLLM server at {POLICY_URL} (set LEAN_SEARCH_POLICY_URL)")
    return model


@pytest.fixture
def served_model_repository(served_model: ServedModel) -> str:
    return served_model.repository


@pytest.fixture
async def policy_client(served_model: ServedModel) -> AsyncIterator[PolicyClient]:
    async with PolicyClient(POLICY_URL, served_model.name) as client:
        yield client
