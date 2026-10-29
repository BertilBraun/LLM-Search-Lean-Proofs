import dataclasses
from collections.abc import Callable

import pytest
from graph_trees import GraphBuilder

from lean_search.search import TreeRecord
from lean_search.search.graph_labels import NodeClass, label_graph
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkPairKind,
    BenchmarkScores,
    BenchmarkState,
    LabelledTree,
    SearchGuidance,
    TreeProvenance,
    TreeSource,
    ValueBenchmark,
    benchmark_fingerprint,
    build_benchmark,
)
from lean_search.value.bins import BIN_COUNT, Readout
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets
from lean_search.value.pair_statistics import (
    PairStatistic,
    PairStatisticConfig,
    labelled_pairs,
    pair_share,
    pair_statistic,
    remaining_steps,
)

CONFIG = BenchmarkConfig()
VALUE_FREE = TreeProvenance("benchmark", SearchGuidance.VALUE_FREE, None, "")


def sibling_tree(problem_name: str) -> TreeRecord:
    """A proof-graph child with a dead-end sibling, an explored off-graph sibling and a never-expanded one."""
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ p")
    dead = builder.child(builder.root, "⊢ d")
    builder.failure(dead)
    expanded = builder.child(builder.root, "⊢ e")
    below = builder.child(expanded, "⊢ f")
    builder.child(below, "⊢ g")
    builder.child(builder.root, "⊢ n")
    return dataclasses.replace(builder.record(builder.child(proof_child)), problem_name=problem_name)


def labelled_tree(record: TreeRecord) -> LabelledTree:
    labels = label_graph(record)
    estimates = recorded_estimates(record, RemainingStepsReadout())
    return LabelledTree(record, labels, value_targets(record, labels, estimates, ValueTargetConfig()))


def benchmark(problems: int) -> ValueBenchmark:
    trees = tuple(labelled_tree(sibling_tree(f"t{number}")) for number in range(problems))
    return build_benchmark([TreeSource(VALUE_FREE, trees)], CONFIG)


def steps_bins(steps: int) -> tuple[float, ...]:
    return tuple(float(index == steps - 1) for index in range(BIN_COUNT))


def scores(bench: ValueBenchmark, proof_steps: Callable[[BenchmarkState], int]) -> BenchmarkScores:
    """h = proof_steps(state) on proof-graph states, 3 on every other state."""
    distributions = tuple(
        steps_bins(proof_steps(state) if state.node_class == NodeClass.PROOF_GRAPH else 3) for state in bench.states
    )
    return BenchmarkScores("m", benchmark_fingerprint(bench), distributions)


def everywhere(steps: int) -> Callable[[BenchmarkState], int]:
    return lambda state: steps


def odd_problems(first: int, second: int) -> Callable[[BenchmarkState], int]:
    return lambda state: first if int(state.problem_name[1:]) % 2 else second


def test_pairs_put_the_proof_child_over_its_dead_and_explored_siblings() -> None:
    kinds = sorted(pair.kind for pair in labelled_pairs(benchmark(1), CONFIG))
    assert kinds == sorted([BenchmarkPairKind.PROOF_OVER_DEAD_END, BenchmarkPairKind.PROOF_OVER_EXPANDED])


def test_a_never_expanded_sibling_enters_no_pair() -> None:
    bench = benchmark(1)
    others = {bench.states[pair.other].node_class for pair in labelled_pairs(bench, CONFIG)}
    assert NodeClass.NEVER_EXPANDED not in others


def statistic(
    problems: int, model: Callable[[BenchmarkState], int], reference: Callable[[BenchmarkState], int]
) -> PairStatistic:
    bench = benchmark(problems)
    model_steps = remaining_steps(scores(bench, model), Readout())
    reference_steps = remaining_steps(scores(bench, reference), Readout())
    return pair_statistic(bench, model_steps, reference_steps, CONFIG, PairStatisticConfig())


def test_a_model_giving_proof_children_the_lower_h_is_ahead_beyond_the_interval() -> None:
    assert statistic(20, everywhere(1), everywhere(5)).lower > 0


def test_a_model_giving_proof_children_the_higher_h_is_behind_beyond_the_interval() -> None:
    assert statistic(20, everywhere(5), everywhere(1)).upper < 0


def test_the_same_scores_have_an_empty_interval_at_zero() -> None:
    result = statistic(20, everywhere(1), everywhere(1))
    assert (result.lower, result.upper) == (0.0, 0.0)


def test_the_difference_is_model_minus_reference_share() -> None:
    assert statistic(20, everywhere(1), everywhere(5)).difference == 1.0


def test_a_tie_in_h_counts_half() -> None:
    assert statistic(4, everywhere(3), everywhere(5)).model_share == 0.5


def test_the_interval_holds_a_mixed_difference() -> None:
    result = statistic(20, odd_problems(1, 5), everywhere(5))
    assert result.lower < result.difference < result.upper


def test_the_statistic_reports_problems_and_pairs() -> None:
    result = statistic(6, everywhere(1), everywhere(5))
    assert (result.problems, result.pairs) == (6, 12)


def test_pairs_moving_together_count_as_one_effective_pair_per_problem() -> None:
    result = statistic(40, odd_problems(1, 5), odd_problems(5, 1))
    assert result.effective_pairs == pytest.approx(40, rel=0.15)


def test_the_bootstrap_is_reproducible() -> None:
    assert statistic(20, odd_problems(1, 5), everywhere(5)) == statistic(20, odd_problems(1, 5), everywhere(5))


def test_a_benchmark_without_scored_pairs_has_no_difference() -> None:
    bench = benchmark(2)
    unscored = [None] * len(bench.states)
    assert pair_statistic(bench, unscored, unscored, CONFIG, PairStatisticConfig()).difference is None


def test_one_models_share_counts_its_pairs_and_problems() -> None:
    bench = benchmark(3)
    share = pair_share(bench, remaining_steps(scores(bench, everywhere(1)), Readout()), CONFIG)
    assert (share.problems, share.pairs, share.share) == (3, 6, 1.0)
