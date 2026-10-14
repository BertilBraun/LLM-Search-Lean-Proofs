from dataclasses import dataclass, field

from lean_search.retrieval.config import RetrievalConfig


@dataclass(frozen=True)
class PolicyConfig:
    # The served model name, or a LoRA adapter's name when `adapter` is set.
    model: str = ""
    # Hugging Face repository or local checkpoint whose chat template renders the prompts.
    tokenizer: str = ""
    # Requests go round-robin over these servers, which must all serve `model`.
    server_urls: tuple[str, ...] = ("http://127.0.0.1:8000/v1",)
    adapter: str | None = None
    sample_count: int = 16
    temperature: float = 1.0
    top_p: float = 1.0
    max_tokens: int = 256
    thinking: bool = False
    # Appended to the system prompt in thinking mode only, e.g. prompts.BRIEF_THINKING_INSTRUCTION; empty adds nothing.
    thinking_instruction: str = ""
    # Thinking only: a sample cut off by max_tokens inside its thoughts gets the thoughts closed and the block opened,
    # and up to forced_answer_tokens more tokens to write the block (budget forcing).
    force_answer_on_truncation: bool = True
    forced_answer_tokens: int = 256
    few_shot: bool = True
    request_timeout_seconds: float = 900.0
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
