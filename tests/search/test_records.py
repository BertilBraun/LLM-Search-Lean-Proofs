import dataclasses
import json
from pathlib import Path

import pytest
from search_trees import add_child, new_tree

from lean_search.search import (
    Accounting,
    SearchResult,
    StepSource,
    StepStatistics,
    StopReason,
    read_tree,
    tree_record,
    write_tree,
)
from lean_search.search.records import from_json_object, to_json
from lean_search.search.texts import (
    CharacterSpan,
    ExpansionTexts,
    InsertedSpan,
    SampledCompletion,
    SampledTokens,
    TokenSpan,
)
from lean_search.search.tree import Edge

RESULT = SearchResult(
    problem_name="t",
    proved=True,
    stop_reason=StopReason.PROVED,
    proof="intros\nsimp",
    proof_steps=("intros", "simp"),
    proof_sources=(StepSource.AUTOMATION, StepSource.AUTOMATION),
    accounting=Accounting(expansions=2, nodes=3, lean_seconds=0.5),
    solved_at=Accounting(expansions=2, nodes=3, lean_seconds=0.5),
    verification_failures=0,
    max_depth_reached=2,
    step_statistics=(StepStatistics("simp", attempts=2, children=1, proofs=1),),
)


def test_search_result_round_trips_through_json() -> None:
    assert from_json_object(SearchResult, json.loads(to_json(RESULT))) == RESULT


def test_tree_record_round_trips_through_a_compressed_file(tmp_path: Path) -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="intros")
    add_child(tree, child, ())
    record = tree_record(tree, "theorem t : p := by", RESULT)
    write_tree(tmp_path / "t.json.gz", record)
    assert read_tree(tmp_path / "t.json.gz") == record


TOKENS = SampledTokens(
    (11, 12, 21, 31),
    (-0.5, -0.25, None, -1.0),
    (InsertedSpan(CharacterSpan(5, 15), TokenSpan(2, 3)), InsertedSpan(CharacterSpan(20, 24), TokenSpan(4, 4))),
)


def test_tree_record_with_per_tactic_goals_and_tokens_round_trips(tmp_path: Path) -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="intros")
    tree.edges[0] = dataclasses.replace(tree.edges[0], tactic_goals=(("⊢ q",),))
    completion = SampledCompletion(0, "Explain.\n\n```lean\nintros\n```", (CharacterSpan(19, 25),), False, TOKENS)
    tree.expansion_texts.append(ExpansionTexts("t", child.node_id, "<prompt>", (completion,), 0.8, 1.0))
    record = tree_record(tree, "theorem t : p := by", RESULT)
    write_tree(tmp_path / "t.json.gz", record)
    assert read_tree(tmp_path / "t.json.gz") == record


def without(record: object, *keys: str) -> dict[str, object]:
    data = json.loads(to_json(record))
    for key in keys:
        del data[key]
    return data


def test_edges_written_before_per_tactic_goals_read_without_them() -> None:
    tree = new_tree("⊢ p")
    add_child(tree, tree.root, ("⊢ q",))
    assert from_json_object(Edge, without(tree.edges[0], "tactic_goals")).tactic_goals == ()


def test_completions_written_before_tokens_read_without_tokens() -> None:
    completion = SampledCompletion(0, "simp", (), True, TOKENS)
    assert from_json_object(SampledCompletion, without(completion, "tokens")).tokens == SampledTokens()


def test_expansion_texts_written_before_sampling_settings_read_as_unknown() -> None:
    texts = ExpansionTexts("t", 0, "<prompt>", (), 0.8, 1.0)
    loaded = from_json_object(ExpansionTexts, without(texts, "temperature", "top_p"))
    assert (loaded.temperature, loaded.top_p) == (None, None)


def test_expansion_texts_written_before_the_policy_version_read_without_it() -> None:
    texts = ExpansionTexts("t", 0, "<prompt>", (), 0.8, 1.0, 2)
    assert from_json_object(ExpansionTexts, without(texts, "policy_version")).policy_version is None


def test_results_written_before_harvesting_read_with_zero_counts() -> None:
    data = json.loads(to_json(RESULT))
    for key in ("proofs", "harvest_expansions", "exploration_expansions"):
        del data["accounting"][key]
    accounting = from_json_object(SearchResult, data).accounting
    assert (accounting.proofs, accounting.harvest_expansions, accounting.exploration_expansions) == (0, 0, 0)


def test_nodes_written_before_value_distributions_read_without_one() -> None:
    tree = new_tree("⊢ p")
    record = tree_record(tree, "theorem t : p := by", RESULT)
    node = record.nodes[0]
    assert from_json_object(type(node), without(node, "value_distribution")).value_distribution is None


def test_tree_record_keeps_the_value_distribution(tmp_path: Path) -> None:
    tree = new_tree("⊢ p")
    tree.root.value_distribution = (0.5, 0, 0, 0, 0, 0, 0, 0.25, 0.25)
    write_tree(tmp_path / "t.json.gz", tree_record(tree, "theorem t : p := by", RESULT))
    assert read_tree(tmp_path / "t.json.gz").nodes[0].value_distribution == (0.5, 0, 0, 0, 0, 0, 0, 0.25, 0.25)


def test_reading_without_texts_leaves_out_only_the_expansions(tmp_path: Path) -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="intros")
    completion = SampledCompletion(0, "Explain.\n\n```lean\nintros\n```", (CharacterSpan(19, 25),), False, TOKENS)
    tree.expansion_texts.append(ExpansionTexts("t", child.node_id, "<prompt>", (completion,), 0.8, 1.0))
    record = tree_record(tree, "theorem t : p := by", RESULT)
    write_tree(tmp_path / "t.json.gz", record)
    assert read_tree(tmp_path / "t.json.gz", texts=False) == dataclasses.replace(record, expansions=())


def test_whole_numbers_in_a_list_of_optional_floats_read_as_floats() -> None:
    tokens = from_json_object(SampledTokens, {"token_ids": [1, 2], "log_probabilities": [0, None]})
    assert [type(value) for value in tokens.log_probabilities] == [float, type(None)]


@pytest.mark.parametrize(
    "data",
    [{"token_ids": [1, "2"]}, {"token_ids": [1, True]}, {"token_ids": [1], "log_probabilities": ["0.5"]}],
    ids=["string", "boolean", "string log-probability"],
)
def test_a_wrong_element_in_a_list_of_numbers_is_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"SampledTokens\.\w+\[\d\]"):
        from_json_object(SampledTokens, data)
