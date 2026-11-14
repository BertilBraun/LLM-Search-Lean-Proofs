"""Two settings step 1 measures before its runs (DESIGN.md, "Follow-up study: controlled arms", "Step 1"): the
generated-token cap T of the reasoning comparison, and the value-free search's automation constant per step
log-probability setting.

The constant follows row 2's rule, the median step log-probability of the steps that made progress, taken as the
value-free search sees it: per edge (a block's value is the best of its merged samples', `policy/prompts.parse_samples`)
and at every depth (root steps score 6-11 nats above deeper ones, review AI). It is computed offline from an ordinary
run's trees (v0 with value v0, which never reads a step's log-probability), each setting's value from the recorded
sampled tokens through the production functions (`parse_sample_block`, `sample_log_probability`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from lean_search.policy.client import Sample
from lean_search.policy.config import StepLogProbability
from lean_search.policy.prompts import NormalizedBlock, parse_sample_block, sample_log_probability
from lean_search.search import SearchResult, StepSource, TreeRecord
from lean_search.search.texts import SampledCompletion, TokenDecoder
from lean_search.search.tree import Edge, EdgeOutcome

# T = 16 x the anchor's mean generated tokens per expansion; T64 the same at miniF2F's 64.
TOKEN_CAP_EXPANSIONS = 16
MINIF2F_TOKEN_CAP_EXPANSIONS = 64
# A recorded sample stopped normally or ran into the token cap with its block complete; parsing treats both alike.
RECORDED_FINISH_REASON = "stop"


@dataclass(frozen=True)
class TokenBudget:
    searches: int
    expansions: int
    generated_tokens: int

    @property
    def tokens_per_expansion(self) -> float:
        return self.generated_tokens / self.expansions

    def cap(self, expansions: int) -> int:
        return round(expansions * self.tokens_per_expansion)


def token_budget(results: Iterable[SearchResult]) -> TokenBudget:
    """The searches' generated tokens over their expansions (a ratio of sums: long searches weigh by their length)."""
    accounted = [result.accounting for result in results]
    return TokenBudget(
        len(accounted),
        sum(accounting.expansions for accounting in accounted),
        sum(accounting.generated_tokens for accounting in accounted),
    )


def progressing_edges(record: TreeRecord) -> list[Edge]:
    """The policy steps that ran completely and changed the goals, each once (a repeated block is its first run)."""
    return [
        edge
        for edge in record.edges
        if edge.source == StepSource.POLICY
        and edge.repeat_of is None
        and edge.failure is None
        and edge.outcome != EdgeOutcome.REJECTED
        and edge.target_id is not None
        and record.nodes[edge.target_id].goals != record.nodes[edge.parent_id].goals
    ]


def recorded_sample(completion: SampledCompletion) -> Sample:
    """The sample as the policy client returned it, from what the tree keeps of it."""
    log_probabilities = [value for value in completion.tokens.log_probabilities if value is not None]
    return Sample(
        completion.text,
        sum(log_probabilities),
        len(completion.tokens.token_ids),
        RECORDED_FINISH_REASON,
        completion.tokens,
    )


def step_value(
    completions: Sequence[SampledCompletion], setting: StepLogProbability, decoder: TokenDecoder, visible: bool
) -> float | None:
    """The best of the merged samples' values under `setting`, a sample whose tokens do not align keeping its
    completion's (as `parse_samples` does); None when no recorded sample parses."""
    values = []
    for completion in completions:
        sample = recorded_sample(completion)
        match parse_sample_block(sample, thinking=False, visible=visible):
            case NormalizedBlock() as block:
                value = sample_log_probability(sample, block, setting, decoder)
                values.append(sample.cumulative_logprob if value is None else value)
    return max(values) if values else None


def progressing_step_values(
    record: TreeRecord, setting: StepLogProbability, decoder: TokenDecoder, visible: bool
) -> list[float]:
    """Per progressing edge its step value under `setting`. Completion is the value the run itself recorded (it searched
    with completion); the block settings come from the edge's recorded samples."""
    completions: dict[int, list[SampledCompletion]] = {}
    for expansion in record.expansions:
        for completion in expansion.completions:
            completions.setdefault(completion.edge_id, []).append(completion)
    values = []
    for edge in progressing_edges(record):
        match setting:
            case StepLogProbability.COMPLETION:
                value = edge.log_probability
            case StepLogProbability.BLOCK_SUM | StepLogProbability.BLOCK_MEAN:
                value = step_value(completions.get(edge.edge_id, []), setting, decoder, visible)
        if value is not None:
            values.append(value)
    return values


@dataclass(frozen=True)
class AutomationConstant:
    setting: StepLogProbability
    edges: int
    # Row 2's rule: the median step log-probability of the steps that made progress.
    constant: float

    @property
    def table(self) -> str:
        """The entry of [value_free_priority] automation_constants (`probe_evaluation.AutomationConstant`)."""
        return (
            f"# The median step log-probability of {self.edges} policy steps that made progress (calibration run).\n"
            "[[value_free_priority.automation_constants]]\n"
            f'step_log_probability = "{self.setting}"\n'
            f"automation_log_probability = {self.constant:.3g}\n"
            "calibrated = true\n"
        )


def automation_constant(setting: StepLogProbability, values: Sequence[float]) -> AutomationConstant:
    if not values:
        raise ValueError(f"No policy step made progress under {setting}.")
    return AutomationConstant(setting, len(values), float(np.median(values)))
