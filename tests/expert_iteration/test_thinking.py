from pathlib import Path

from expert_trees import TreeBuilder
from loop_fixtures import attempt

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.digests import (
    DigestConfig,
    digest_new_shards,
    digested,
    read_contexts,
    read_policy,
)
from lean_search.expert_iteration.preferences import ValueJumpConfig
from lean_search.expert_iteration.shards import Decision, ShardWriter, read_attempt_reasoning, read_attempts
from lean_search.expert_iteration.thinking import StepReasoning, TreeReasoning, edge_reasoning
from lean_search.expert_iteration.thinking_expander import ReasoningLog, most_likely_reasoning
from lean_search.policy.client import Sample
from lean_search.search import TreeRecord
from lean_search.value.labels import TreeLabelConfig

DIGESTS = DigestConfig(PreferenceConfig(), False, ValueJumpConfig(enabled=False), TreeLabelConfig(), 16)


def sample(reasoning: str, block: str, log_probability: float) -> Sample:
    return Sample(f"{reasoning}\n</think>\n\n```lean\n{block}\n```", log_probability, 50, "stop")


def test_a_block_keeps_the_reasoning_of_its_most_likely_sample() -> None:
    samples = [sample("guess", "simp", -3.0), sample("the goal is linear", "simp", -1.0), sample("x", "ring", -2.0)]
    reasoning = most_likely_reasoning(samples, ["simp", "simp", "ring"])
    assert reasoning == {"simp": "the goal is linear", "ring": "x"}


def test_samples_without_a_block_give_no_reasoning() -> None:
    assert most_likely_reasoning([sample("lost", "simp", -1.0)], [None]) == {}


def test_a_finished_search_takes_its_reasoning_once() -> None:
    log = ReasoningLog()
    log.add("a.t", 0, {"simp": "because"})
    taken = log.take("a.t")
    assert (taken, log.take("a.t")) == ([StepReasoning(0, "simp", "because")], [])


def proved_tree() -> TreeRecord:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    builder.failure(builder.root, "exact foo")
    proved = builder.child(builder.root, step="linarith")
    return builder.record(proved)


STEPS = (StepReasoning(0, "linarith", "it is linear"), StepReasoning(0, "exact foo", "maybe foo"))
REASONING = TreeReasoning("import Mathlib", STEPS)


def test_reasoning_joins_the_edges_by_node_and_block() -> None:
    record = proved_tree()
    texts = {edge.edge_id: edge.text for edge in record.edges}
    joined = {texts[edge_id]: reasoning for edge_id, reasoning in edge_reasoning(record, STEPS).items()}
    assert joined == {"linarith": "it is linear", "exact foo": "maybe foo"}


def test_the_reasoning_file_reads_back(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.t", proved=True, decision=Decision.SOLVED), proved_tree(), REASONING)
    writer.close()
    (shard,) = [path for path in tmp_path.iterdir() if path.is_dir()]
    (record,) = read_attempts(shard)
    assert read_attempt_reasoning(shard, record) == REASONING


def test_pairs_carry_the_reasoning_of_both_steps(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path / "shards", max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.t", proved=True, decision=Decision.SOLVED), proved_tree(), REASONING)
    writer.close()
    digest_new_shards(tmp_path / "shards", tmp_path / "digests", DIGESTS)
    (digest,) = digested(tmp_path / "digests")
    pairs = [versioned.pair for versioned in read_policy(digest)]
    assert [(pair.chosen_reasoning, pair.rejected_reasoning) for pair in pairs] == [("it is linear", "maybe foo")]


def two_step_tree() -> TreeRecord:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    middle = builder.child(builder.root, "⊢ s", step="intro x")
    builder.failure(middle, "exact foo")
    proved = builder.child(middle, step="linarith")
    return builder.record(proved)


def test_a_thinking_pair_keeps_the_state_before_its_step(tmp_path: Path) -> None:
    reasoning = TreeReasoning(
        "import Mathlib", (StepReasoning(1, "linarith", "linear"), StepReasoning(1, "exact foo", "foo"))
    )
    writer = ShardWriter(tmp_path / "shards", max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.t", proved=True, decision=Decision.SOLVED), two_step_tree(), reasoning)
    writer.close()
    digest_new_shards(tmp_path / "shards", tmp_path / "digests", DIGESTS)
    (digest,) = digested(tmp_path / "digests")
    (context,) = read_contexts(digest)
    assert (context.previous_steps, context.goals, context.reference_goals) == (("intro x",), ("⊢ s",), ((),))
