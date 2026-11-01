import dataclasses
import functools
import random
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from test_policy_data import CharacterTokenizer, completion, forced_completion

from lean_search.lean import ProofState
from lean_search.policy.prompts import render_prompt
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin, write_examples
from lean_search.rl.expert_iteration_data import (
    CompletionFilter,
    CompletionSelector,
    ExpertIterationDataConfig,
    ProofGraphCompletion,
    ReplayConfig,
    SpaceRequirement,
    TreeCompletions,
    data_summary,
    examples_within_completion_tokens,
    proof_graph_completions,
    read_completions,
    replay_token_budgets,
    selected_completions,
    space_shortages,
    training_data,
    write_completions,
)
from lean_search.rl.policy_data import PolicyDataConfig, build_policy_data
from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data
from lean_search.search import (
    Accounting,
    EdgeOutcome,
    Failure,
    FailureKind,
    SearchResult,
    SearchTree,
    StepSource,
    StopReason,
    TreeRecord,
    tree_record,
)
from lean_search.search.graph_labels import goal_key
from lean_search.search.texts import ExpansionTexts, SampledCompletion, SampledTokens
from lean_search.search.tree import Node
from lean_search.training.math_data import MathSolution, write_solutions
from lean_search.training.sft_data import SftExample, TokenizedExample

ROOT = "a b : ℕ\nh₀ : a = b\n⊢ a + 0 = b"
MIDDLE = "a b : ℕ\nh₀ : a = b\n⊢ a = b"
DETOUR = "a b : ℕ\nh₀ : a = b\n⊢ b = b"
CLAIM = "a b : ℕ\nh₀ : a = b\n⊢ b = a"
AFTER_CLAIM = "a b : ℕ\nh₀ : a = b\nh : b = a\n⊢ a + 0 = b"
# From the root: one step to MIDDLE, then one to the proof; the root is two steps from it.
FIRST_STEP = "rw [Nat.add_zero]"
SHORTEST = "rw [Nat.add_zero]\nexact h₀"
DETOURING = "rw [Nat.add_zero]\nrw [h₀]\nrfl"
FAILING = "linarith"
VERSION = 5
CONFIG = ExpertIterationDataConfig(validation_fraction=0.0)
KEEP_ALL = CompletionFilter(minimum_version=VERSION)
TOKENIZER = CharacterTokenizer()
type Sampler = Callable[[int, str], SampledCompletion]


def proof_state(*goals: str) -> ProofState:
    return ProofState("", "theorem t (a b : ℕ) (h₀ : a = b) : a + 0 = b := by", (), goals, 0, 0)


class TreeBuilder:
    """A search tree with each expansion's recorded samples, one per block."""

    def __init__(self, problem_name: str = "p", root: str = ROOT) -> None:
        self.tree = SearchTree(problem_name, proof_state(root), 0.0)
        self.tree.root.expansion_index = 0
        self.samples: dict[tuple[int, bool], list[SampledCompletion]] = {}

    def block(
        self,
        parent_id: int,
        text: str,
        states: Sequence[tuple[str, ...]],
        *,
        feedback: bool = False,
        sampled: Sampler = completion,
    ) -> int:
        """A block whose tactics reach `states` in turn, the last a new node's or an existing one's; its node id."""
        parent = self.expanded(parent_id)
        existing = self.tree.node_with_goals(goal_key(states[-1])) if states[-1] else None
        edge = self.tree.add_edge(
            parent,
            text=text,
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.CHILD if existing is None else EdgeOutcome.DUPLICATE,
            target_id=self.tree.next_node_id() if existing is None else existing.node_id,
            applied_tactics=len(states),
            total_tactics=len(states),
            tactic_goals=tuple(states),
            feedback=feedback,
        )
        self.samples.setdefault((parent_id, feedback), []).append(sampled(edge.edge_id, text))
        if existing is not None:
            return existing.node_id
        child = self.tree.add_child(parent, edge.edge_id, text, StepSource.POLICY, -1.0, proof_state(*states[-1]), 0, 0)
        if not states[-1]:
            self.tree.mark_proof_path(child)
        return child.node_id

    def failure(self, parent_id: int, text: str = FAILING) -> None:
        edge = self.tree.add_edge(
            self.expanded(parent_id),
            text=text,
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.FAILED,
            total_tactics=1,
            failure=Failure(FailureKind.ERROR, "linarith failed"),
        )
        self.samples.setdefault((parent_id, False), []).append(completion(edge.edge_id, text))

    def expanded(self, node_id: int) -> Node:
        node = self.tree.node(node_id)
        node.expansion_index = node_id
        return node

    def record(self, version: int | None = VERSION) -> TreeRecord:
        for (node_id, feedback), samples in self.samples.items():
            prompt = render_prompt(TOKENIZER, self.tree.node(node_id).goals, visible=True)
            self.tree.expansion_texts.append(
                ExpansionTexts(
                    self.tree.problem_name, node_id, prompt, tuple(samples), policy_version=version, feedback=feedback
                )
            )
        self.tree.settle_statuses()
        result = SearchResult("p", True, StopReason.PROVED, None, (), (), Accounting(expansions=1), None, 0, 1)
        return tree_record(self.tree, "theorem t", result)


def root_with(text: str, states: Sequence[tuple[str, ...]], sampled: Sampler = completion) -> TreeBuilder:
    """The root's shortest proof and a failing sample beside the given block."""
    builder = TreeBuilder()
    middle = builder.block(0, FIRST_STEP, [(MIDDLE,)])
    builder.block(middle, "exact h₀", [()])
    builder.failure(0)
    builder.block(0, text, states, sampled=sampled)
    return builder


def kept_blocks(record: TreeRecord, completion_filter: CompletionFilter = KEEP_ALL) -> list[str]:
    completions = proof_graph_completions(record, TOKENIZER, CONFIG, completion_filter).completions
    return [completion.block for completion in completions]


def root_blocks(record: TreeRecord, completion_filter: CompletionFilter = KEEP_ALL) -> list[str]:
    completions = proof_graph_completions(record, TOKENIZER, CONFIG, completion_filter).completions
    return [completion.block for completion in completions if completion.goals == (ROOT,)]


def test_a_block_whose_every_tactic_is_on_the_proof_graph_is_selected() -> None:
    assert SHORTEST in root_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record())


def test_a_block_with_a_failing_tactic_is_not_selected() -> None:
    assert FAILING not in root_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record())


def test_a_proof_graph_block_off_the_shortest_route_is_not_selected() -> None:
    assert DETOURING not in root_blocks(root_with(DETOURING, [(MIDDLE,), (DETOUR,), ()]).record())


def test_a_block_leaving_a_claim_open_is_not_selected() -> None:
    builder = TreeBuilder()
    claimed = builder.block(0, "have h : b = a", [(CLAIM, AFTER_CLAIM)])
    builder.block(claimed, "exact h₀.symm\nexact h ▸ rfl", [(AFTER_CLAIM,), ()])
    assert root_blocks(builder.record()) == []


def loop_and_expert_examples() -> tuple[TokenizedExample, TokenizedExample]:
    """The shortest block at the root as the loop trains on it and as expert iteration does."""
    record = root_with(SHORTEST, [(MIDDLE,), ()]).record()
    labelled = label_phase_data([record], TrainingPhaseConfig())
    data = build_policy_data(labelled.policy_trees, TOKENIZER, PolicyDataConfig())
    shortest_edge = next(edge.edge_id for edge in record.edges if edge.text == SHORTEST)
    loop = next(sequence.tokenized for sequence in data.sequences if sequence.edge_id == shortest_edge)
    completions = proof_graph_completions(record, TOKENIZER, CONFIG, KEEP_ALL).completions
    expert = next(completion.tokenized for completion in completions if completion.block == SHORTEST)
    return loop, expert


def test_the_example_equals_the_loop_sequence_token_for_token() -> None:
    loop, expert = loop_and_expert_examples()
    assert expert.input_ids == loop.input_ids


def test_the_prompt_token_count_equals_the_loop_sequence() -> None:
    loop, expert = loop_and_expert_examples()
    assert expert.prompt_token_count == loop.prompt_token_count


def test_samples_of_a_rejected_version_are_not_selected() -> None:
    rejecting = CompletionFilter(minimum_version=VERSION, rejected_versions=frozenset({VERSION + 1}))
    assert kept_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record(version=VERSION + 1), rejecting) == []


@pytest.mark.parametrize("version", [VERSION - 1, None])
def test_samples_before_the_minimum_version_are_not_selected(version: int | None) -> None:
    assert kept_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record(version=version)) == []


def test_feedback_round_samples_are_not_selected() -> None:
    builder = TreeBuilder()
    middle = builder.block(0, FIRST_STEP, [(MIDDLE,)])
    builder.block(middle, "exact h₀", [()])
    builder.block(0, SHORTEST, [(MIDDLE,), ()], feedback=True)
    assert SHORTEST not in root_blocks(builder.record())


def undecodable(edge_id: int, block: str) -> SampledCompletion:
    return dataclasses.replace(completion(edge_id, block), tokens=SampledTokens((ord("x"),), (-0.5,)))


@pytest.mark.parametrize(
    "sampled",
    [
        pytest.param(forced_completion, id="forced answer"),
        pytest.param(functools.partial(completion, recorded=False), id="no recorded tokens"),
        pytest.param(undecodable, id="tokens not decoding to the text"),
    ],
)
def test_samples_not_trainable_as_sampled_are_not_selected(sampled: Sampler) -> None:
    assert SHORTEST not in root_blocks(root_with(SHORTEST, [(MIDDLE,), ()], sampled).record())


def test_held_out_statements_are_never_selected() -> None:
    held_out = CompletionFilter(minimum_version=VERSION, held_out_statements=frozenset({"p"}))
    assert kept_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record(), held_out) == []


def test_states_equal_to_a_held_out_state_are_never_selected() -> None:
    held_out = CompletionFilter(minimum_version=VERSION, held_out_goal_keys=frozenset({goal_key((ROOT,))}))
    assert root_blocks(root_with(SHORTEST, [(MIDDLE,), ()]).record(), held_out) == []


def tree_completions(record: TreeRecord, below_band: bool = False) -> TreeCompletions:
    return proof_graph_completions(record, TOKENIZER, CONFIG, KEEP_ALL, below_band)


def selected(
    trees: Sequence[TreeCompletions], config: ExpertIterationDataConfig = CONFIG
) -> list[ProofGraphCompletion]:
    selection = selected_completions(trees, config)
    return [*selection.train, *selection.validation]


def test_a_state_searched_twice_is_kept_once() -> None:
    tree = tree_completions(root_with(SHORTEST, [(MIDDLE,), ()]).record())
    assert len(selected([tree, tree])) == len(selected([tree]))


def chain(problem_name: str, length: int) -> TreeRecord:
    """A proof of `length` one-tactic steps, each state with a failing sample beside its step."""
    builder = TreeBuilder(problem_name, "n : ℕ\n⊢ goal 0")
    node_id = 0
    for step in range(1, length + 1):
        builder.failure(node_id)
        node_id = builder.block(node_id, f"step {step}", [(f"n : ℕ\n⊢ goal {step}",) if step < length else ()])
    return builder.record()


def test_states_per_statement_are_capped() -> None:
    config = dataclasses.replace(CONFIG, states_per_statement=3)
    assert len(selected([tree_completions(chain("p", 8))], config)) == 3


def root_proofs(texts: Sequence[str], failures: int, problem_name: str = "p") -> TreeRecord:
    """The root proved in one tactic by each text, beside `failures` failing samples."""
    builder = TreeBuilder(problem_name)
    for _ in range(failures):
        builder.failure(0)
    for text in texts:
        builder.block(0, text, [()])
    return builder.record()


def test_blocks_per_state_are_capped() -> None:
    assert len(selected([tree_completions(root_proofs(["simp", "omega", "exact h₀"], 1))])) == CONFIG.blocks_per_state


def test_the_selector_holds_at_most_the_capped_blocks_of_a_state() -> None:
    selector = CompletionSelector(CONFIG)
    for texts in (["simp", "omega"], ["exact h₀", "trivial"], ["norm_num", "decide"]):
        selector.add(tree_completions(root_proofs(texts, 1)))
    assert len(selector.blocks["p", goal_key((ROOT,))]) == CONFIG.blocks_per_state


@pytest.mark.parametrize(
    ("second_tree_failures", "easy"),
    [pytest.param(1, True, id="7 of 8 pooled"), pytest.param(2, False, id="6 of 8 pooled")],
)
def test_easy_states_pool_their_samples_over_the_trees(second_tree_failures: int, easy: bool) -> None:
    first = tree_completions(root_proofs(["simp", "omega", "exact h₀", "trivial"], 0))
    proofs = ["norm_num", "decide", "rfl"][: 4 - second_tree_failures]
    second = tree_completions(root_proofs(proofs, second_tree_failures))
    assert selected_completions([first, second], CONFIG).easy_states == int(easy)


def one_step_statement(problem_name: str, easy: bool) -> TreeCompletions:
    return tree_completions(root_proofs(["simp"] if easy else ["omega", "simp"], 0 if easy else 1, problem_name))


def test_easy_states_stay_within_their_share() -> None:
    hard = [one_step_statement(f"hard{number}", easy=False) for number in range(4)]
    easy = [one_step_statement(f"easy{number}", easy=True) for number in range(5)]
    examples = selected([*hard, *easy])
    assert sum(example.easy for example in examples) / len(examples) <= CONFIG.max_easy_share


def test_examples_record_that_their_statement_came_from_below_the_band() -> None:
    tree = tree_completions(root_with(SHORTEST, [(MIDDLE,), ()]).record(), below_band=True)
    assert data_summary(selected_completions([tree], CONFIG)).below_band_share == 1.0


def test_validation_and_training_statements_are_disjoint() -> None:
    config = dataclasses.replace(CONFIG, validation_fraction=0.5)
    selection = selected_completions([one_step_statement(f"s{number}", False) for number in range(20)], config)
    train = {completion.problem_name for completion in selection.train}
    assert train.isdisjoint(completion.problem_name for completion in selection.validation)


def test_written_examples_read_back_equal(tmp_path: Path) -> None:
    completions = list(tree_completions(chain("p", 3)).completions)
    write_completions(tmp_path / "train.jsonl", completions)
    assert read_completions(tmp_path / "train.jsonl") == completions


def test_selection_is_deterministic_for_a_seed() -> None:
    trees = [tree_completions(chain(f"s{number}", 4)) for number in range(6)]
    shuffled = random.Random(1).sample(trees, len(trees))
    assert selected_completions(shuffled, CONFIG) == selected_completions(trees, CONFIG)


def test_replay_examples_stop_once_their_completion_tokens_reach_the_budget() -> None:
    examples = [TokenizedExample(SftExample("replay", str(number), 0, (), ""), (1,) * 10, 5) for number in range(10)]
    assert len(examples_within_completion_tokens(examples, lambda example: example, 12, "seed")) == 3


REPLAY = ReplayConfig(
    lean_replay="lean.jsonl",
    math_replay="math.jsonl",
    lean_token_share=0.3,
    math_token_share=0.1,
    validation="lean_validation.jsonl",
    validation_examples=3,
)


def written_training_files(root: Path) -> Path:
    """The build's expert-iteration files and the replay files, as `train` reads them; returns the data directory."""
    completions = list(tree_completions(chain("p", 4)).completions)
    directory = root / "grpo_expert_iteration" / "round"
    write_completions(directory / "train.jsonl", completions[:3])
    write_completions(directory / "validation.jsonl", completions[3:])
    reasoning = [
        ReasoningExample("replay", f"proof{number}", 0, (ROOT,), "simp", "Idea.", "", ReasoningOrigin.SAMPLED, True)
        for number in range(40)
    ]
    write_examples(root / "lean.jsonl", reasoning)
    write_examples(root / "lean_validation.jsonl", reasoning[:5])
    write_solutions(root / "math.jsonl", [MathSolution("math", str(number), "1 + 1?", "2") for number in range(40)])
    return directory


def test_training_data_holds_the_expert_iteration_examples(tmp_path: Path) -> None:
    data = training_data(TOKENIZER, written_training_files(tmp_path), REPLAY, tmp_path)
    assert len(data.expert_iteration) == 3


def test_training_data_draws_the_replay_validation_set_apart(tmp_path: Path) -> None:
    data = training_data(TOKENIZER, written_training_files(tmp_path), REPLAY, tmp_path)
    assert (len(data.expert_iteration_validation), len(data.replay_validation)) == (1, REPLAY.validation_examples)


def test_training_data_replays_lean_at_its_completion_token_share(tmp_path: Path) -> None:
    data = training_data(TOKENIZER, written_training_files(tmp_path), REPLAY, tmp_path)
    expert_tokens = sum(example.completion_token_count for example in data.expert_iteration)
    lean_budget, _ = replay_token_budgets(expert_tokens, REPLAY)
    lean_tokens = sum(example.completion_token_count for example in data.lean_replay)
    assert (
        lean_budget <= lean_tokens < lean_budget + max(example.completion_token_count for example in data.lean_replay)
    )


def test_training_data_trains_on_every_part(tmp_path: Path) -> None:
    data = training_data(TOKENIZER, written_training_files(tmp_path), REPLAY, tmp_path)
    assert len(data.train) == len(data.expert_iteration) + len(data.lean_replay) + len(data.math_replay)


def test_space_shortages_name_a_directory_without_the_space(tmp_path: Path) -> None:
    assert space_shortages([SpaceRequirement(tmp_path, 1e12, "a test")]) != []
