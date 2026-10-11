from dataclasses import dataclass, field

from lean_search.value.bins import Readout


@dataclass(frozen=True)
class ValueConfig:
    # The served base model; set, the value model replaces priority.value_estimator as A*'s h.
    model: str = ""
    # Hugging Face repository or local checkpoint whose chat template renders the prompts.
    tokenizer: str = ""
    # Requests go round-robin over these servers, which must all serve `model` and the adapter.
    server_urls: tuple[str, ...] = ("http://127.0.0.1:8000/v1",)
    # The value LoRA adapter's served name, e.g. loaded with `--lora-modules <name>=<path>`.
    adapter: str | None = None
    # Logprobs vLLM returns per request (its default --max-logprobs is 20); bins outside them get the smallest.
    top_k: int = 20
    readout: Readout = field(default_factory=Readout)
    request_timeout_seconds: float = 300.0
