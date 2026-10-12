"""Value v1 data: the labels of every round tree, proofs of automation-only trees, and replayed traced labels."""

from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.expert_iteration.config import ValueDataConfig
from lean_search.expert_iteration.mixing import replay_amount, sample_value_examples
from lean_search.expert_iteration.pool import problem_source
from lean_search.search import TreeRecord
from lean_search.value.labels import LabelKind, TreeLabelConfig, ValueExample, merge_duplicates, tree_examples


@dataclass(frozen=True)
class ValueMixture:
    train: list[ValueExample]
    # Distinct states from each part before the final merge.
    tree_states: int
    prefilter_states: int
    replay_states: int


def carries_no_loss(example: ValueExample) -> bool:
    """`at least 1` (open frontier states): every distribution satisfies it, so its loss is zero."""
    return example.kind == LabelKind.AT_LEAST and example.steps <= 1


def round_tree_examples(record: TreeRecord, config: TreeLabelConfig) -> list[ValueExample]:
    examples = tree_examples(record, problem_source(record.problem_name), config)
    return [example for example in examples if not carries_no_loss(example)]


def prefilter_tree_examples(record: TreeRecord, config: TreeLabelConfig) -> list[ValueExample]:
    """Automation-only trees: their proofs bound the remaining steps, their dead ends say nothing about the policy."""
    examples = tree_examples(record, problem_source(record.problem_name), config)
    return [example for example in examples if example.kind == LabelKind.EXACT]


def value_mixture(
    tree: Sequence[ValueExample],
    prefilter: Sequence[ValueExample],
    replay: Sequence[ValueExample],
    config: ValueDataConfig,
    seed: str,
) -> ValueMixture:
    """Round tree states, a capped share of pre-filter proof states, then replay as `replay_fraction` of the total."""
    tree_states = merge_duplicates(tree)
    prefilter_count = round(len(tree_states) * config.prefilter_fraction)
    prefilter_states = sample_value_examples(merge_duplicates(prefilter), prefilter_count, seed)
    replay_count = replay_amount(len(tree_states) + len(prefilter_states), config.replay_fraction)
    replay_states = sample_value_examples(replay, replay_count, seed)
    train = merge_duplicates([*tree_states, *prefilter_states, *replay_states])
    return ValueMixture(train, len(tree_states), len(prefilter_states), len(replay_states))
