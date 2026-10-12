import pytest
from expert_trees import TreeBuilder

from lean_search.expert_iteration.config import ValueDataConfig
from lean_search.expert_iteration.mixing import is_held_out, replay_amount, sample_value_examples
from lean_search.expert_iteration.value_data import prefilter_tree_examples, round_tree_examples, value_mixture
from lean_search.search import TreeRecord
from lean_search.value.labels import LabelKind, TreeLabelConfig, ValueExample

LABELS = TreeLabelConfig()


def mixed_tree() -> TreeRecord:
    """Root -> a (dead), b (expanded, child c open), d -> proof."""
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    builder.failure(a, "simp")
    b = builder.child(builder.root, "⊢ b")
    builder.child(b, "⊢ c")
    d = builder.child(builder.root, "⊢ d")
    proved = builder.child(d)
    return builder.record(proved)


def examples(count: int, source: str = "traced") -> list[ValueExample]:
    return [
        ValueExample((f"⊢ {source} {index}",), LabelKind.EXACT, 1, 1.0, source, f"{source}/{index}", 0)
        for index in range(count)
    ]


def test_round_labels_drop_the_open_frontier() -> None:
    labels = {(example.goals[0], example.kind, example.steps) for example in round_tree_examples(mixed_tree(), LABELS)}
    assert labels == {
        ("⊢ r", LabelKind.EXACT, 2),
        ("⊢ a", LabelKind.DEAD, 0),
        ("⊢ b", LabelKind.AT_LEAST, 2),
        ("⊢ d", LabelKind.EXACT, 1),
    }


def test_round_labels_name_the_pool_source() -> None:
    assert {example.source for example in round_tree_examples(mixed_tree(), LABELS)} == {"lean_workbook"}


def test_prefilter_trees_give_only_exact_labels() -> None:
    assert {example.goals[0] for example in prefilter_tree_examples(mixed_tree(), LABELS)} == {"⊢ r", "⊢ d"}


def test_replay_makes_up_the_configured_share() -> None:
    config = ValueDataConfig(replay_fraction=0.25, prefilter_fraction=0.0)
    mixture = value_mixture(examples(30, "tree"), [], examples(100), config, "seed")
    assert mixture.replay_states == 10


def test_prefilter_states_are_capped_by_their_share() -> None:
    config = ValueDataConfig(replay_fraction=0.0, prefilter_fraction=0.1)
    mixture = value_mixture(examples(30, "tree"), examples(50, "prefilter"), [], config, "seed")
    assert mixture.prefilter_states == 3


def test_the_mixture_merges_states_seen_twice() -> None:
    config = ValueDataConfig(replay_fraction=0.5, prefilter_fraction=0.0)
    shared = examples(10)
    assert len(value_mixture(shared, [], shared, config, "seed").train) == 10


@pytest.mark.parametrize(("new", "fraction", "replay"), [(100, 0.0, 0), (100, 0.5, 100), (90, 0.25, 30), (10, 0.9, 90)])
def test_replay_amount(new: int, fraction: float, replay: int) -> None:
    assert replay_amount(new, fraction) == replay


@pytest.mark.parametrize(("fraction", "held_out"), [(0.0, False), (1.0, True)])
def test_held_out_fraction_bounds(fraction: float, held_out: bool) -> None:
    assert is_held_out("lean_workbook.t", "seed", fraction) is held_out


def test_held_out_share_is_close_to_the_fraction() -> None:
    held_out = sum(is_held_out(f"p{index}", "seed", 0.1) for index in range(10_000))
    assert 900 < held_out < 1100


def test_samples_do_not_depend_on_the_input_order() -> None:
    pool = examples(50)
    assert sample_value_examples(pool, 10, "seed") == sample_value_examples(pool[::-1], 10, "seed")
