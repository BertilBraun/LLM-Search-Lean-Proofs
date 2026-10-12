"""The policy expander in thinking mode, keeping the reasoning behind each block for training (thinking.py)."""

from collections.abc import Sequence

from lean_search.expert_iteration.thinking import StepReasoning
from lean_search.policy.client import Sample
from lean_search.policy.expander import MINIMUM_GENERATED_TOKENS, PolicyExpander, candidate_batch
from lean_search.policy.prompts import parse_sample, parse_samples, render_prompt
from lean_search.reasoning.thinking import reasoning_text
from lean_search.search import CandidateBatches, Node, SearchContext


def most_likely_reasoning(samples: Sequence[Sample], sample_blocks: Sequence[str | None]) -> dict[str, str]:
    """Per block, the reasoning of the most likely sample that wrote it."""
    best: dict[str, Sample] = {}
    for sample, block in zip(samples, sample_blocks, strict=True):
        if block is not None and (block not in best or sample.cumulative_logprob > best[block].cumulative_logprob):
            best[block] = sample
    return {block: reasoning_text(sample.text) for block, sample in best.items()}


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
    """PolicyExpander.expand that also logs each block's reasoning; belongs in the policy expander once it keeps it."""

    def __init__(self, inner: PolicyExpander, log: ReasoningLog) -> None:
        self.inner = inner
        self.log = log

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        inner = self.inner
        config = inner.config
        lemmas = await inner.lemma_provider.lemma_lines(node.state, context.repl) if inner.lemma_provider else ()
        prompt = render_prompt(
            inner.tokenizer,
            node.goals,
            lemmas,
            few_shot=config.few_shot,
            thinking=config.thinking,
            thinking_instruction=config.thinking_instruction,
        )
        prompt_tokens = len(inner.tokenizer.encode(prompt, add_special_tokens=False))
        max_tokens = min(config.max_tokens, inner.max_model_length - prompt_tokens)
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            inner.statistics.prompts_too_long += 1
            return
        generation, seconds = await inner._generate(prompt, max_tokens)
        parsed = parse_samples(generation.samples, thinking=config.thinking, forbidden_tokens=inner.forbidden_tokens)
        inner.statistics.record(generation, parsed, seconds)
        sample_blocks = [
            block
            if isinstance(block := parse_sample(sample, thinking=True, forbidden_tokens=inner.forbidden_tokens), str)
            else None
            for sample in generation.samples
        ]
        self.log.add(context.problem.name, node.node_id, most_likely_reasoning(generation.samples, sample_blocks))
        yield candidate_batch(parsed, generation)
