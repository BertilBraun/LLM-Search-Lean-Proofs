"""Two settings step 1 measures before its runs (DESIGN.md, "Follow-up study: controlled arms", "Step 1"): the
generated-token cap T of the reasoning comparison, and the value-free search's automation constant per step
log-probability setting."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from lean_search.policy.config import StepLogProbability
from lean_search.rl.single_step import root_samples
from lean_search.search import SearchResult, TreeRecord
from lean_search.search.graph_labels import goal_key

# T = 16 x the anchor's mean generated tokens per expansion; T64 the same at miniF2F's 64.
TOKEN_CAP_EXPANSIONS = 16
MINIF2F_TOKEN_CAP_EXPANSIONS = 64


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


@dataclass(frozen=True)
class StepValue:
    log_probability: float
    samples: int


def progressing_step_values(record: TreeRecord) -> list[StepValue]:
    """The root's policy blocks that ran completely and changed the goals, with their recorded step value (the
    setting's, the best of the merged samples) and the samples behind them."""
    root = goal_key(record.nodes[0].goals)
    return [
        StepValue(sample.edge.log_probability, sample.sample_count)
        for sample in root_samples(record, frozenset())
        if sample.valid
        and sample.reached is not None
        and sample.reached != root
        and sample.edge.log_probability is not None
    ]


@dataclass(frozen=True)
class AutomationConstant:
    setting: StepLogProbability
    samples: int
    # Row 2's rule: the median step log-probability of the samples that made progress.
    constant: float

    @property
    def table(self) -> str:
        return (
            f"# The median step log-probability of {self.samples} samples that made progress.\n"
            "[value_free_priority]\n"
            "length_exponent = 1.0\n"
            f'step_log_probability = "{self.setting}"\n'
            f"automation_log_probability = {self.constant:.3g}\n"
        )


def automation_constant(setting: StepLogProbability, values: Sequence[StepValue]) -> AutomationConstant:
    """Each sample counts once: a merged block weighs by its samples."""
    if not values:
        raise ValueError(f"No sample made progress under {setting}.")
    per_sample = np.repeat([value.log_probability for value in values], [value.samples for value in values])
    return AutomationConstant(setting, len(per_sample), float(np.median(per_sample)))
