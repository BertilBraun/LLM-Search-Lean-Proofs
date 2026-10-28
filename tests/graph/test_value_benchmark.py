from pathlib import Path

import pytest
from graph_trees import GraphBuilder

from lean_search.search import TreeRecord
from lean_search.search.graph_labels import NodeClass, label_graph
from lean_search.search.priority import PriorityKind
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkEstimates,
    BenchmarkGroup,
    BenchmarkMetrics,
    BenchmarkScores,
    BenchmarkState,
    EstimateKind,
    LabelledTree,
    SearchGuidance,
    StateEstimate,
    TreeKey,
    TreeProvenance,
    TreeSource,
    ValueBenchmark,
    benchmark_composition,
    benchmark_fingerprint,
    benchmark_metrics,
    build_benchmark,
    fresh_estimates,
    guidance_conflicts,
    looked_up_estimates,
    read_benchmark,
    read_scores,
    recorded_benchmark_estimates,
    search_provenance,
    write_benchmark,
    write_scores,
)
from lean_search.value.bins import Readout
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets

READOUT = RemainingStepsReadout()
VALUE_FREE = TreeProvenance("row2", SearchGuidance.VALUE_FREE, PriorityKind.CUMULATIVE_LOG_PROBABILITY, "")
GUIDED_BY_V0 = TreeProvenance("astar", SearchGuidance.VALUE_MODEL, PriorityKind.A_STAR, "value-v0")
LOG_PROBABILITY_CONFIG = '[priority]\nkind = "cumulative_log_probability"\nautomation_log_probability = -2.8\n'
A_STAR_CONFIG = """
[priority]
kind = "a_star"
value_weight = 1.0

[value]
model = "search-qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
adapter = "value-v0"
"""


def tree_record(with_values: bool = True) -> TreeRecord:
    def value(estimate: float) -> float | None:
        return estimate if with_values else None

    builder = GraphBuilder("⊢ r", root_value=value(3.0))
    proof_child = builder.child(builder.root, "⊢ p", value=value(2.0))
    dead = builder.child(builder.root, "⊢ d", value=value(1.5))
    builder.failure(dead)
    expanded = builder.child(builder.root, "⊢ e", value=value(4.0))
    builder.child(expanded, "⊢ e1", value=value(5.0))
    builder.child(builder.root, "⊢ n", value=value(6.0))
    proof = builder.child(proof_child)
    return builder.record(proof)


def labelled_tree(record: TreeRecord) -> LabelledTree:
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, READOUT), ValueTargetConfig())
    return LabelledTree(record, labels, targets)


def tree_benchmark(provenance: TreeProvenance = VALUE_FREE, config: BenchmarkConfig | None = None) -> ValueBenchmark:
    return build_benchmark([TreeSource(provenance, (labelled_tree(tree_record()),))], config or BenchmarkConfig())


def test_log_probability_search_is_value_free() -> None:
    provenance = search_provenance("row2", LOG_PROBABILITY_CONFIG, [tree_record(with_values=False)])
    assert provenance.guidance == SearchGuidance.VALUE_FREE


def test_a_star_search_names_its_value_adapter() -> None:
    assert search_provenance("astar", A_STAR_CONFIG, [tree_record()]).value_model == "value-v0"


def test_a_merged_value_model_is_named_by_its_served_model() -> None:
    config = A_STAR_CONFIG.replace('adapter = "value-v0"\n', "").replace("search-qwen3.5-2b", "value-merged")
    assert search_provenance("visible", config, [tree_record()]).value_model == "value-merged"


def test_trees_with_estimates_and_no_config_count_as_guided_by_an_unknown_value() -> None:
    assert search_provenance("visible", None, [tree_record()]).guidance == SearchGuidance.UNKNOWN_VALUE


def test_trees_without_estimates_and_no_config_are_value_free() -> None:
    assert search_provenance("row2", None, [tree_record(with_values=False)]).guidance == SearchGuidance.VALUE_FREE


def test_a_value_free_config_contradicted_by_recorded_estimates_is_rejected() -> None:
    with pytest.raises(ValueError):
        search_provenance("row2", LOG_PROBABILITY_CONFIG, [tree_record()])


@pytest.mark.parametrize(
    ("provenance", "compared", "conflicting"),
    [
        (GUIDED_BY_V0, ["value-v0"], True),
        (GUIDED_BY_V0, ["value-v1"], False),
        (GUIDED_BY_V0, None, True),
        (VALUE_FREE, None, False),
        (TreeProvenance("goal count", SearchGuidance.HEURISTIC_VALUE, PriorityKind.A_STAR, "goal_count"), None, False),
        (TreeProvenance("visible", SearchGuidance.UNKNOWN_VALUE, None, ""), ["value-v1"], True),
    ],
    ids=["compared", "other model", "any value model", "value free", "heuristic", "unknown"],
)
def test_guidance_conflicts(provenance: TreeProvenance, compared: list[str] | None, conflicting: bool) -> None:
    assert bool(guidance_conflicts([provenance], compared)) is conflicting


def test_benchmark_records_the_provenance_of_its_trees() -> None:
    assert tree_benchmark(GUIDED_BY_V0).provenance == (GUIDED_BY_V0,)


def test_benchmark_holds_every_sibling_state_with_goals() -> None:
    assert benchmark_composition(tree_benchmark(), BenchmarkConfig()).states == 5


def test_benchmark_includes_never_expanded_children() -> None:
    assert benchmark_composition(tree_benchmark(), BenchmarkConfig()).never_expanded == 2


def test_benchmark_keeps_one_tree_per_statement() -> None:
    sources = [
        TreeSource(VALUE_FREE, (labelled_tree(tree_record()),)),
        TreeSource(GUIDED_BY_V0, (labelled_tree(tree_record()),)),
    ]
    benchmark = build_benchmark(sources, BenchmarkConfig())
    assert {state.run for state in benchmark.states} == {"row2"}


def test_benchmark_round_trips_through_its_file(tmp_path: Path) -> None:
    benchmark = tree_benchmark()
    write_benchmark(tmp_path / "benchmark.json.gz", benchmark)
    assert read_benchmark(tmp_path / "benchmark.json.gz") == benchmark


def test_per_tree_cap_keeps_proof_graph_groups() -> None:
    benchmark = tree_benchmark(config=BenchmarkConfig(max_states_per_tree=1))
    assert benchmark_composition(benchmark, BenchmarkConfig()).groups_with_proof_state == 1


def test_recorded_estimates_are_the_recorded_h() -> None:
    record = tree_record()
    benchmark = tree_benchmark()
    estimates = recorded_benchmark_estimates(benchmark, {TreeKey("row2", "t"): record})
    assert estimates.estimates[0] == StateEstimate(None, record.nodes[benchmark.states[0].node_id].value_estimate)


def recorded_metrics(provenance: TreeProvenance) -> BenchmarkMetrics:
    benchmark = tree_benchmark(provenance)
    estimates = recorded_benchmark_estimates(benchmark, {TreeKey(provenance.run, "t"): tree_record()})
    return benchmark_metrics(benchmark, estimates, BenchmarkConfig())


def test_recorded_estimates_on_value_guided_trees_are_flagged_circular() -> None:
    assert recorded_metrics(GUIDED_BY_V0).circular_runs == ("astar",)


def test_recorded_estimates_describe_their_bias() -> None:
    assert "biased if the trees were guided by this model" in recorded_metrics(GUIDED_BY_V0).estimates


def test_recorded_estimates_get_no_calibration() -> None:
    metrics = recorded_metrics(GUIDED_BY_V0)
    assert (metrics.calibration, metrics.separation) == (None, None)


def test_estimates_looked_up_from_another_search_are_not_circular() -> None:
    benchmark = tree_benchmark(VALUE_FREE)
    estimates = looked_up_estimates(benchmark, [tree_record()], "value-v0")
    assert benchmark_metrics(benchmark, estimates, BenchmarkConfig()).circular_runs == ()


def test_estimates_are_looked_up_by_statement_and_goals() -> None:
    benchmark = tree_benchmark(VALUE_FREE)
    estimates = looked_up_estimates(benchmark, [tree_record()], "value-v0")
    by_goals = {state.goals: estimate for state, estimate in zip(benchmark.states, estimates.estimates, strict=True)}
    assert by_goals[("⊢ e",)] == StateEstimate(None, 4.0)


def test_fresh_scores_of_the_guiding_model_are_flagged_circular() -> None:
    benchmark = tree_benchmark(GUIDED_BY_V0)
    distribution = (0.5, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25)
    scores = BenchmarkScores("value-v0", benchmark_fingerprint(benchmark), (distribution,) * len(benchmark.states))
    metrics = benchmark_metrics(benchmark, fresh_estimates(benchmark, scores, Readout()), BenchmarkConfig())
    assert metrics.circular_runs == ("astar",)


def test_fresh_estimates_read_the_proof_probability_from_the_dead_bin() -> None:
    benchmark = tree_benchmark()
    distribution = (0.5, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25)
    scores = BenchmarkScores("m", benchmark_fingerprint(benchmark), (distribution,) * len(benchmark.states))
    assert fresh_estimates(benchmark, scores, Readout()).estimates[0] == StateEstimate(0.75, 4 / 3)


def test_scores_made_for_another_benchmark_are_rejected() -> None:
    benchmark = tree_benchmark()
    scores = BenchmarkScores("m", "another", (None,) * len(benchmark.states))
    with pytest.raises(ValueError):
        fresh_estimates(benchmark, scores, Readout())


def test_scores_round_trip_through_their_file(tmp_path: Path) -> None:
    scores = BenchmarkScores("m", "fingerprint", ((0.5, 0.5), None))
    write_scores(tmp_path / "scores.json.gz", scores)
    assert read_scores(tmp_path / "scores.json.gz") == scores


def hand_built_metrics() -> BenchmarkMetrics:
    """A proof-graph state with a dead end, an explored and an unexplored expanded sibling, and two never expanded."""
    states = (
        BenchmarkState("row2", "t", 1, ("⊢ p",), NodeClass.PROOF_GRAPH, 1.0, 1, 1),
        BenchmarkState("row2", "t", 2, ("⊢ d",), NodeClass.DEAD_END, 0.0, None, 1),
        BenchmarkState("row2", "t", 3, ("⊢ e",), NodeClass.EXPANDED_OFF_GRAPH, 0.5, None, 3),
        BenchmarkState("row2", "t", 4, ("⊢ u",), NodeClass.EXPANDED_OFF_GRAPH, None, None, 1),
        BenchmarkState("row2", "t", 5, ("⊢ n",), NodeClass.NEVER_EXPANDED, None, None, 0),
        BenchmarkState("row2", "t", 6, ("⊢ m",), NodeClass.NEVER_EXPANDED, None, None, 0),
    )
    benchmark = ValueBenchmark((VALUE_FREE,), states, (BenchmarkGroup("row2", "t", 0, (0, 1, 2, 3, 4, 5)),))
    estimates = (
        StateEstimate(0.9, 1.5),
        StateEstimate(0.95, 1.2),
        StateEstimate(0.2, 9.0),
        StateEstimate(0.99, 1.0),
        StateEstimate(0.99, 1.0),
        None,
    )
    return benchmark_metrics(benchmark, BenchmarkEstimates(EstimateKind.FRESH, "m", estimates), BenchmarkConfig())


def test_only_siblings_with_a_known_label_pair_with_the_proof_state() -> None:
    assert hand_built_metrics().ranking.pairs == 2


def test_pairwise_ranking_accuracy() -> None:
    assert hand_built_metrics().ranking.pairwise_accuracy == 0.5


def test_ranking_accuracy_over_dead_ends() -> None:
    assert hand_built_metrics().ranking.proof_over_dead_end.accuracy == 0.0


def test_ranking_accuracy_over_explored_expanded_siblings() -> None:
    assert hand_built_metrics().ranking.proof_over_expanded.accuracy == 1.0


def test_expanded_siblings_rank_over_dead_ends_as_their_own_pair_type() -> None:
    assert hand_built_metrics().ranking.expanded_over_dead_end.pairs == 1


def test_never_expanded_siblings_are_counted_but_not_paired() -> None:
    assert hand_built_metrics().ranking.never_expanded_siblings == 2


def test_unexplored_expanded_siblings_are_counted_but_not_paired() -> None:
    assert hand_built_metrics().ranking.unexplored_expanded_siblings == 1


def test_top_accuracy_needs_the_proof_state_above_every_labelled_sibling() -> None:
    assert hand_built_metrics().ranking.top_accuracy == 0.0


def test_states_without_estimate_are_counted() -> None:
    assert hand_built_metrics().states_without_estimate == 1


def test_anchor_calibration_error() -> None:
    calibration = hand_built_metrics().calibration
    assert calibration is not None and calibration.anchor_expected_calibration_error == pytest.approx(0.425)


def test_anchor_brier_score() -> None:
    calibration = hand_built_metrics().calibration
    assert calibration is not None and calibration.anchor_brier_score == pytest.approx((0.1**2 + 0.95**2) / 2)


def test_dead_live_separation() -> None:
    separation = hand_built_metrics().separation
    assert separation is not None and separation.proof_graph_over_dead_end_auc == 0.0


def test_remaining_step_error_on_proof_graph_states() -> None:
    assert hand_built_metrics().steps.mean_absolute_error == pytest.approx(0.5)
