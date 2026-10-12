"""Short reasoning: rewriting traces with a same-family model; checking that a short trace still leads to a step."""

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.lean import ProofState
from lean_search.policy.client import ChatMessage, PolicyClient, Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyTokenizer, load_tokenizer
from lean_search.policy.prompts import (
    FENCE,
    LENGTH_FINISH_REASON,
    THINK_END,
    THINK_START,
    parse_sample,
    render_prompt,
    thinking_prefill,
    user_message,
)
from lean_search.reasoning.pipeline import FORBIDDEN, LeanExecutor, LeanTask, LeanTaskResult
from lean_search.reasoning.reward import RewardConfig, is_success
from lean_search.reasoning.states import GoalKey

REWRITER_SYSTEM_PROMPT = "You are a Lean 4 and Mathlib expert who writes short, precise reasoning for proof steps."
# Shorter quotes of the goal or the step are ordinary in reasoning; longer ones restate it.
MINIMUM_QUOTED_CHARACTERS = 24


class RewriteMode(StrEnum):
    # Shorten a sampled reasoning trace that led to the step.
    COMPRESS = "compress"
    # Write a short reasoning for a step that was found without one.
    RATIONALIZE = "rationalize"


class RewriteDefect(StrEnum):
    TRUNCATED = "truncated"
    EMPTY = "empty"
    THINK_TAG = "think_tag"
    CODE_BLOCK = "code_block"
    TOO_LONG = "too_long"
    COPIES_STEP = "copies_step"
    RESTATES_GOAL = "restates_goal"


@dataclass(frozen=True)
class RewriteConfig:
    # The served model that rewrites, without thinking (e.g. the base model, no adapter).
    model: str = ""
    # Hugging Face repository whose chat template renders the rewriting prompt and counts tokens.
    tokenizer: str = ""
    server_urls: tuple[str, ...] = ("http://127.0.0.1:8000/v1",)
    adapter: str | None = None
    # The length asked for in the instruction.
    target_tokens: int = 150
    # Rewrites longer than this are rejected.
    max_accepted_tokens: int = 200
    max_tokens: int = 320
    candidates: int = 2
    temperature: float = 0.7
    top_p: float = 1.0
    requests_in_flight: int = 128
    request_timeout_seconds: float = 600.0


@dataclass(frozen=True)
class RewriteRequest:
    goals: tuple[str, ...]
    tactic_block: str
    # The trace to shorten; empty when rationalizing.
    reasoning: str


@dataclass(frozen=True)
class Rewrite:
    text: str
    tokens: int
    defect: RewriteDefect | None


def rewrite_instruction(mode: RewriteMode, target_tokens: int) -> str:
    rules = (
        f"Use at most {target_tokens} tokens: the key insight and why this step fits the proof state. Never restate "
        "the goal or the hypotheses, do not copy the step's code and write no code blocks. Reply with the reasoning "
        "only."
    )
    match mode:
        case RewriteMode.COMPRESS:
            return f"Rewrite the reasoning above, which led to the step, much shorter. {rules}"
        case RewriteMode.RATIONALIZE:
            return f"Write the reasoning that leads to the step above. {rules}"


def rewrite_messages(request: RewriteRequest, mode: RewriteMode, target_tokens: int) -> list[ChatMessage]:
    sections = [user_message(request.goals)]
    if mode == RewriteMode.COMPRESS:
        sections.append(f"Reasoning:\n{request.reasoning.strip()}")
    sections.append(f"Step:\n```lean\n{request.tactic_block}\n```")
    sections.append(rewrite_instruction(mode, target_tokens))
    return [ChatMessage("system", REWRITER_SYSTEM_PROMPT), ChatMessage("user", "\n\n".join(sections))]


def collapsed(text: str) -> str:
    return " ".join(text.split())


def restates_goal(text: str, goals: Sequence[str]) -> bool:
    conclusions = [collapsed(goal.rpartition("⊢")[2]) for goal in goals]
    return any(
        len(conclusion) >= MINIMUM_QUOTED_CHARACTERS and conclusion in collapsed(text) for conclusion in conclusions
    )


def copies_step(text: str, tactic_block: str) -> bool:
    step = collapsed(tactic_block)
    return len(step) >= MINIMUM_QUOTED_CHARACTERS and step in collapsed(text)


def rewrite_defect(
    text: str, finish_reason: str, tokens: int, request: RewriteRequest, max_accepted_tokens: int
) -> RewriteDefect | None:
    if finish_reason == LENGTH_FINISH_REASON:
        return RewriteDefect.TRUNCATED
    if not text:
        return RewriteDefect.EMPTY
    if THINK_START in text or THINK_END in text:
        return RewriteDefect.THINK_TAG
    if FENCE in text:
        return RewriteDefect.CODE_BLOCK
    if tokens > max_accepted_tokens:
        return RewriteDefect.TOO_LONG
    if copies_step(text, request.tactic_block):
        return RewriteDefect.COPIES_STEP
    if restates_goal(text, request.goals):
        return RewriteDefect.RESTATES_GOAL
    return None


class ReasoningRewriter:
    def __init__(self, config: RewriteConfig, tokenizer: PolicyTokenizer, clients: Sequence[PolicyClient]) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self._clients = itertools.cycle(clients)
        self._semaphore = asyncio.Semaphore(config.requests_in_flight)

    async def rewrite(self, request: RewriteRequest, mode: RewriteMode) -> tuple[Rewrite, ...]:
        conversation = [
            {"role": message.role, "content": message.content}
            for message in rewrite_messages(request, mode, self.config.target_tokens)
        ]
        prompt = self.tokenizer.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        async with self._semaphore:
            generation = await next(self._clients).generate(
                prompt,
                sample_count=self.config.candidates,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                adapter=self.config.adapter,
            )
        return tuple(self.rewrite_of(sample, request) for sample in generation.samples)

    def rewrite_of(self, sample: Sample, request: RewriteRequest) -> Rewrite:
        text = sample.text.strip()
        tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        defect = rewrite_defect(text, sample.finish_reason, tokens, request, self.config.max_accepted_tokens)
        return Rewrite(text, tokens, defect)


@contextlib.asynccontextmanager
async def open_rewriter(config: RewriteConfig) -> AsyncIterator[ReasoningRewriter]:
    tokenizer = load_tokenizer(config.tokenizer)
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(url, config.model, timeout_seconds=config.request_timeout_seconds)
            )
            for url in config.server_urls
        ]
        yield ReasoningRewriter(config, tokenizer, clients)


@dataclass(frozen=True)
class SufficiencyConfig:
    # Empty samples through the policy's own servers.
    server_urls: tuple[str, ...] = ()
    sample_count: int = 4
    temperature: float = 0.8
    top_p: float = 1.0
    max_tokens: int = 256


@dataclass(frozen=True)
class SufficiencyItem:
    """Given reasoning, prefilled as the policy's thoughts on the proof state, judged against a reference proof."""

    proof_state: ProofState
    reference_goal_keys: tuple[GoalKey, ...]
    reasoning: str


@dataclass(frozen=True)
class SufficiencyCheck:
    # Per sample, the block it wrote after the given reasoning, or None when it wrote no usable block.
    blocks: tuple[str | None, ...]
    lean: LeanTaskResult
    # Samples whose block succeeded.
    successes: int

    @property
    def sufficient(self) -> bool:
        return self.successes > 0


def sufficiency_check(blocks: Sequence[str | None], lean: LeanTaskResult, reward: RewardConfig) -> SufficiencyCheck:
    succeeded = {
        execution.tactic_block
        for execution in lean.executions
        if is_success(execution.outcome, execution.reference_steps_advanced, execution.value_drop, reward)
    }
    return SufficiencyCheck(tuple(blocks), lean, sum(block in succeeded for block in blocks))


class SufficiencyChecker:
    def __init__(
        self,
        policy: PolicyConfig,
        config: SufficiencyConfig,
        reward: RewardConfig,
        tokenizer: PolicyTokenizer,
        clients: Sequence[PolicyClient],
        executor: LeanExecutor,
        requests_in_flight: int,
    ) -> None:
        self.policy = policy
        self.config = config
        self.reward = reward
        self.tokenizer = tokenizer
        self.executor = executor
        self._clients = itertools.cycle(clients)
        self._semaphore = asyncio.Semaphore(requests_in_flight)

    async def sample_blocks(self, item: SufficiencyItem) -> tuple[str | None, ...]:
        prompt = render_prompt(
            self.tokenizer,
            item.proof_state.goals,
            few_shot=self.policy.few_shot,
            thinking=True,
            thinking_instruction=self.policy.thinking_instruction,
        ) + thinking_prefill(item.reasoning)
        async with self._semaphore:
            generation = await next(self._clients).generate(
                prompt,
                sample_count=self.config.sample_count,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                stop=(FENCE,),
                adapter=self.policy.adapter,
            )
        # The prefill opens the block, so each sample is a block up to its closing fence.
        parsed = [parse_sample(sample, thinking=False, forbidden_tokens=FORBIDDEN) for sample in generation.samples]
        return tuple(block if isinstance(block, str) else None for block in parsed)

    async def check(self, items: Sequence[SufficiencyItem]) -> list[SufficiencyCheck]:
        sampled = await asyncio.gather(*(self.sample_blocks(item) for item in items))
        tasks = [
            LeanTask(item.proof_state, item.reference_goal_keys, tuple(dict.fromkeys(b for b in blocks if b)))
            for item, blocks in zip(items, sampled, strict=True)
        ]
        results = await self.executor.run(tasks)
        return [sufficiency_check(blocks, result, self.reward) for blocks, result in zip(sampled, results, strict=True)]


@contextlib.asynccontextmanager
async def open_sufficiency_checker(
    policy: PolicyConfig,
    config: SufficiencyConfig,
    reward: RewardConfig,
    executor: LeanExecutor,
    requests_in_flight: int,
) -> AsyncIterator[SufficiencyChecker]:
    tokenizer = load_tokenizer(policy.tokenizer)
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(url, policy.model, timeout_seconds=policy.request_timeout_seconds)
            )
            for url in config.server_urls or policy.server_urls
        ]
        yield SufficiencyChecker(policy, config, reward, tokenizer, clients, executor, requests_in_flight)
