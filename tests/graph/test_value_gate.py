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
from lean_search.value.gate_statistics import GateConfig, GateResult, labelled_pairs, value_gate
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets

CONFIG = BenchmarkConfig()
VALUE_FREE = TreeProvenance("gate", SearchGuidance.VALUE_FREE, None, "")


def gate_tree(problem_name: str) -> TreeRecord:
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
    trees = tuple(labelled_tree(gate_tree(f"t{number}")) for number in range(problems))
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


def gate(
    problems: int, candidate: Callable[[BenchmarkState], int], current: Callable[[BenchmarkState], int]
) -> GateResult:
    bench = benchmark(problems)
    return value_gate(bench, scores(bench, candidate), scores(bench, current), Readout(), CONFIG, GateConfig())


def test_a_candidate_giving_proof_children_the_lower_h_passes() -> None:
    assert gate(20, everywhere(1), everywhere(5)).passed


def test_a_candidate_giving_proof_children_the_higher_h_fails() -> None:
    assert not gate(20, everywhere(5), everywhere(1)).passed


def test_the_same_scores_have_no_gain_and_fail() -> None:
    result = gate(20, everywhere(1), everywhere(1))
    assert (result.statistic.lower, result.statistic.upper, result.passed) == (0.0, 0.0, False)


def test_the_difference_is_candidate_minus_current_accuracy() -> None:
    assert gate(20, everywhere(1), everywhere(5)).statistic.difference == 1.0


def test_a_tie_in_h_counts_half() -> None:
    assert gate(4, everywhere(3), everywhere(5)).statistic.candidate_accuracy == 0.5


def test_the_interval_holds_a_mixed_difference() -> None:
    statistic = gate(20, odd_problems(1, 5), everywhere(5)).statistic
    assert statistic.lower < statistic.difference < statistic.upper


def test_the_statistic_reports_problems_and_pairs() -> None:
    statistic = gate(6, everywhere(1), everywhere(5)).statistic
    assert (statistic.problems, statistic.pairs) == (6, 12)


def test_pairs_moving_together_count_as_one_effective_pair_per_problem() -> None:
    statistic = gate(40, odd_problems(1, 5), odd_problems(5, 1)).statistic
    assert statistic.effective_pairs == pytest.approx(40, rel=0.15)


def test_the_bootstrap_is_reproducible() -> None:
    first = gate(20, odd_problems(1, 5), everywhere(5)).statistic
    assert gate(20, odd_problems(1, 5), everywhere(5)).statistic == first


def test_a_benchmark_without_scored_pairs_fails() -> None:
    bench = benchmark(2)
    unscored = BenchmarkScores("m", benchmark_fingerprint(bench), (None,) * len(bench.states))
    result = value_gate(bench, unscored, unscored, Readout(), CONFIG, GateConfig())
    assert result.reasons == ("no labelled sibling pair scored by both models",)


def test_a_value_guided_benchmark_fails_the_gate() -> None:
    guided = TreeProvenance("astar", SearchGuidance.VALUE_MODEL, None, "value-v0")
    trees = tuple(labelled_tree(gate_tree(f"t{number}")) for number in range(20))
    bench = build_benchmark([TreeSource(guided, trees)], CONFIG)
    candidate, current = scores(bench, everywhere(1)), scores(bench, everywhere(5))
    assert not value_gate(bench, candidate, current, Readout(), CONFIG, GateConfig()).passed
