"""Shorter reasoning for thinking-mode pairs, through the reasoning module (lean_search.reasoning.compression).

The served base model rewrites each long chosen reasoning shorter (defective rewrites rejected); the policy, given a
rewrite as its thoughts on the proof state, samples steps that Lean runs against the proof's later states; the
shortest rewrite with a working step replaces the reasoning, otherwise it stays as it was.
"""

import asyncio
import contextlib
from collections import Counter
from collections.abc import Sequence

from lean_search.expert_iteration.thinking import CompressionConfig, ThinkingItem
from lean_search.lean import LeanReplConfig, ProofState
from lean_search.policy.config import PolicyConfig
from lean_search.reasoning.compression import (
    ReasoningRewriter,
    RewriteConfig,
    RewriteMode,
    RewriteRequest,
    SufficiencyConfig,
    SufficiencyItem,
    open_rewriter,
    open_sufficiency_checker,
)
from lean_search.reasoning.pipeline import ExecutionConfig, open_executor
from lean_search.reasoning.reward import RewardConfig
from lean_search.reasoning.states import goal_key


def sufficiency_item(item: ThinkingItem, reasoning: str) -> SufficiencyItem:
    context = item.context
    # Session 0 is never live, so the REPL rebuilds the state by replaying the proof's earlier steps.
    # Each earlier step replays under the REPL's default heartbeat limit, at least what the search allowed it.
    replay_heartbeats = (LeanReplConfig().tactic_heartbeats,) * len(context.previous_steps)
    state = ProofState(
        context.header, context.statement, context.previous_steps, context.goals, -1, 0, replay_heartbeats
    )
    return SufficiencyItem(state, tuple(goal_key(goals) for goals in context.reference_goals), reasoning)


class CompressingShortener:
    def __init__(self, config: CompressionConfig, policy: PolicyConfig) -> None:
        self.config = config
        self.policy = policy

    def rewrite_config(self) -> RewriteConfig:
        config = self.config
        return RewriteConfig(
            model=self.policy.model,
            tokenizer=self.policy.tokenizer,
            server_urls=self.policy.server_urls,
            adapter=config.rewriter_adapter,
            target_tokens=config.target_tokens,
            max_accepted_tokens=config.max_accepted_tokens,
            min_accepted_tokens=config.min_accepted_tokens,
            target_ratio=config.target_ratio,
            min_accepted_ratio=config.min_accepted_ratio,
            max_accepted_ratio=config.max_accepted_ratio,
            max_tokens=config.rewrite_max_tokens,
            candidates=config.candidates,
            requests_in_flight=config.requests_in_flight,
        )

    async def shorten(self, items: Sequence[ThinkingItem]) -> list[str]:
        reasoning = [item.pair.chosen_reasoning or "" for item in items]
        if not items:
            return reasoning
        config = self.config
        header = Counter(item.context.header for item in items).most_common(1)[0][0]
        sufficiency = SufficiencyConfig(
            sample_count=config.sufficiency_samples, max_tokens=config.sufficiency_max_tokens
        )
        async with contextlib.AsyncExitStack() as stack:
            rewriter = await stack.enter_async_context(open_rewriter(self.rewrite_config()))
            executor = await stack.enter_async_context(
                open_executor(header, ExecutionConfig(pool_size=config.lean_processes))
            )
            checker = await stack.enter_async_context(
                open_sufficiency_checker(self.policy, sufficiency, RewardConfig(), executor, config.requests_in_flight)
            )
            long = [
                index
                for index, text in enumerate(reasoning)
                if len(rewriter.tokenizer.encode(text, add_special_tokens=False)) > config.min_tokens
            ]
            candidates = await asyncio.gather(*(self.candidates(rewriter, items[index]) for index in long))
            checked = [(index, text) for index, texts in zip(long, candidates, strict=True) for text in texts]
            checks = await checker.check([sufficiency_item(items[index], text) for index, text in checked])
            for (index, text), check in zip(checked, checks, strict=True):
                if check.sufficient and len(text) < len(reasoning[index]):
                    reasoning[index] = text
        return reasoning

    async def candidates(self, rewriter: ReasoningRewriter, item: ThinkingItem) -> list[str]:
        """Non-defective rewrites of the item's reasoning, shortest first."""
        request = RewriteRequest(item.context.goals, item.pair.chosen, item.pair.chosen_reasoning or "")
        rewrites = await rewriter.rewrite(request, RewriteMode.COMPRESS)
        return [
            rewrite.text for rewrite in sorted(rewrites, key=lambda rewrite: rewrite.tokens) if rewrite.defect is None
        ]
