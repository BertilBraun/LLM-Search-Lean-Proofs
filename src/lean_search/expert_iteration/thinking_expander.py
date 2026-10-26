"""The policy expander with reasoning (thinking or visible), keeping the reasoning behind each block for training."""

from collections.abc import Sequence

from lean_search.expert_iteration.thinking import StepReasoning
from lean_search.policy.client import Sample
from lean_search.policy.expander import PolicyExpander
from lean_search.policy.prompts import parse_sample
from lean_search.reasoning.thinking import sample_reasoning
from lean_search.search import CandidateBatches, Node, SearchContext


def most_likely_reasoning(
    samples: Sequence[Sample], sample_blocks: Sequence[str | None], *, visible: bool = False
) -> dict[str, str]:
    """Per block, the reasoning (thoughts, or the visible explanation) of the most likely sample that wrote it."""
    best: dict[str, Sample] = {}
    for sample, block in zip(samples, sample_blocks, strict=True):
        if block is not None and (block not in best or sample.cumulative_logprob > best[block].cumulative_logprob):
            best[block] = sample
    return {
        block: sample_reasoning(sample.text, thinking=not visible, visible=visible) for block, sample in best.items()
    }


class ReasoningLog:
    """Reasoning per in-flight search (statement names are unique among them), taken when the search ends."""

    def __init__(self) -> None:
        self.by_problem: dict[str, list[StepReasoning]] = {}

    def add(self, problem_name: str, node_id: int, reasoning: dict[str, str]) -> None:
        entries = self.by_problem.setdefault(problem_name, [])
        entries.extend(StepReasoning(node_id, block, text) for block, text in reasoning.items())

    def take(self, problem_name: str) -> list[StepReasoning]:
        return self.by_problem.pop(problem_name, [])


class ReasoningExpander:
    """PolicyExpander.expand (forced answers included) that also logs each block's reasoning."""

    def __init__(self, inner: PolicyExpander, log: ReasoningLog) -> None:
        self.inner = inner
        self.log = log

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        inner = self.inner
        sampled = await inner.sample(node, context)
        if sampled is None:
            return
        thinking, visible = inner.config.thinking, inner.config.visible_reasoning
        sample_blocks = [
            block
            if isinstance(
                block := parse_sample(
                    sample, thinking=thinking, forbidden_tokens=inner.forbidden_tokens, visible=visible
                ),
                str,
            )
            else None
            for sample in sampled.samples
        ]
        reasoning = most_likely_reasoning(sampled.samples, sample_blocks, visible=visible)
        self.log.add(context.problem.name, node.node_id, reasoning)
        yield inner.batch(sampled)
