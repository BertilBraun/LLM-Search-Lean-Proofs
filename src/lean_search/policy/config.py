from dataclasses import dataclass, field

from lean_search.retrieval.config import RetrievalConfig


@dataclass(frozen=True)
class FeedbackConfig:
    """After an expansion's samples ran: when they gave fewer than `min_children` new states, some failed with an error
    and none proved the node, one more request at the node whose prompt adds up to `max_attempts` of the samples'
    failed blocks (as sampled) with the first lines of Lean's errors."""

    enabled: bool = False
    min_children: int = 2
    max_attempts: int = 2
    sample_count: int = 4
    max_block_characters: int = 400
    max_error_characters: int = 300
    # False: the blind control, the same trigger and samples on the node's own prompt (still marked feedback).
    show_attempts: bool = True


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
    # Thinking off; the reply explains the key idea briefly and then gives the block (prompts.VISIBLE_SYSTEM_PROMPT).
    visible_reasoning: bool = False
    # Appended to the system prompt in thinking mode only, e.g. prompts.BRIEF_THINKING_INSTRUCTION; empty adds nothing.
    thinking_instruction: str = ""
    # Thinking or visible reasoning: a sample cut off by max_tokens before its block gets its reasoning closed and the
    # block opened, and up to forced_answer_tokens more tokens to write the block (budget forcing).
    force_answer_on_truncation: bool = True
    forced_answer_tokens: int = 256
    few_shot: bool = True
    request_timeout_seconds: float = 900.0
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    # One prompt line naming the automation tactics that failed at the node; the automation must finish first.
    failed_automation_in_prompt: bool = False

    @property
    def reasons(self) -> bool:
        return self.thinking or self.visible_reasoning


def policy_config_problem(config: PolicyConfig) -> str | None:
    if config.thinking_instruction and not config.thinking:
        return "policy.thinking_instruction is only used with policy.thinking = true."
    if config.visible_reasoning and (config.thinking or config.few_shot):
        return "policy.visible_reasoning excludes policy.thinking and policy.few_shot."
    feedback = config.feedback
    if min(feedback.min_children, feedback.max_attempts, feedback.sample_count) < 1:
        return "policy.feedback needs min_children, max_attempts and sample_count of at least 1."
    if min(feedback.max_block_characters, feedback.max_error_characters) < 16:
        return "policy.feedback needs max_block_characters and max_error_characters of at least 16."
    return None
