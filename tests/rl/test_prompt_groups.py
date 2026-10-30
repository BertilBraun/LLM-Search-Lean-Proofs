from test_policy_data import CharacterTokenizer, completion

from lean_search.lean import ProofState
from lean_search.lean.identifiers import NameRepair
from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig
from lean_search.rl.policy_data import ExpansionTexts, PolicyDataConfig, PolicyTree, build_policy_data
from lean_search.rl.single_step import reference_labels, single_step_groups
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

STATEMENT = "theorem t (a b : ℕ) (h₀ : a = b) : a + 0 = b := by"
ROOT = "a b : ℕ\nh₀ : a = b\n⊢ a + 0 = b"
REFERENCE_NEXT = "a b : ℕ\nh₀ : a = b\n⊢ a = b"
REFERENCE_STEPS = {goal_key((REFERENCE_NEXT,)): 1, (): 0}
REWARDS = RewardConfig()
REPAIRED = "rw [Nat.add_zero, h₀]"


def state(*goals: str) -> ProofState:
    return ProofState("", STATEMENT, ("intro",), goals, 0, 0)


def add_sample(
    tree: SearchTree, text: str, reaches: bool, *, feedback: bool = False, repairs: tuple[NameRepair, ...] = ()
) -> None:
    """A root sample reaching the reference's next state (first a new child, then duplicates) or failing."""
    root = tree.root
    if not reaches:
        tree.add_edge(
            root,
            text=text,
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.FAILED,
            total_tactics=1,
            failure=Failure(FailureKind.ERROR, "linarith failed"),
            feedback=feedback,
            name_repairs=repairs,
        )
        return
    new = len(tree.nodes) == 1
    edge = tree.add_edge(
        root,
        text=text,
        source=StepSource.POLICY,
        log_probability=-1.0,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.CHILD if new else EdgeOutcome.DUPLICATE,
        target_id=tree.next_node_id() if new else 1,
        applied_tactics=1,
        total_tactics=1,
        tactic_goals=((REFERENCE_NEXT,),),
        feedback=feedback,
        name_repairs=repairs,
    )
    if new:
        tree.add_child(root, edge.edge_id, text, StepSource.POLICY, -1.0, state(REFERENCE_NEXT), 0.0, 0.0)


def feedback_tree() -> TreeRecord:
    """Edges 0-1 the first round's, 2-3 the feedback round's, 4 a first-round sample whose name was repaired."""
    tree = SearchTree("t", state(ROOT), 0.0)
    tree.root.expansion_index = 0
    add_sample(tree, "simp only [Nat.add_zero]", True)
    add_sample(tree, "linarith", False)
    add_sample(tree, "rw [Nat.add_zero]", True, feedback=True)
    add_sample(tree, "omega", False, feedback=True)
    add_sample(tree, REPAIRED, True, repairs=(NameRepair("Nat.add_zeroo", "Nat.add_zero"),))
    tree.settle_statuses()
    result = SearchResult("t", False, StopReason.EXPANSION_BUDGET, None, (), (), Accounting(expansions=1), None, 0, 1)
    return tree_record(tree, STATEMENT, result)


def root_groups() -> list[PolicyGroup]:
    record = feedback_tree()
    labels, tactics = reference_labels(record, REFERENCE_STEPS, REWARDS.off_graph_min_expanded_nodes)
    return list(single_step_groups(record, labels, tactics, REWARDS).groups)


def test_feedback_samples_form_a_group_of_their_own() -> None:
    assert [(group.feedback, [sample.text for sample in group.samples]) for group in root_groups()] == [
        (False, ["simp only [Nat.add_zero]", "linarith"]),
        (True, ["rw [Nat.add_zero]", "omega"]),
    ]


def test_repaired_sample_is_in_no_group() -> None:
    assert all(REPAIRED not in [sample.text for sample in group.samples] for group in root_groups())


def prompts_by_edge() -> dict[int, str]:
    texts = (
        ExpansionTexts("t", 0, "prompt", (completion(0, "simp only [Nat.add_zero]"), completion(1, "linarith"))),
        ExpansionTexts("t", 0, "feedback", (completion(2, "rw [Nat.add_zero]"), completion(3, "omega")), feedback=True),
    )
    data = build_policy_data([PolicyTree(tuple(root_groups()), texts)], CharacterTokenizer(), PolicyDataConfig())
    return {
        sequence.edge_id: "".join(map(chr, sequence.tokenized.input_ids[: sequence.tokenized.prompt_token_count]))
        for sequence in data.sequences
    }


def test_each_sample_trains_on_the_prompt_it_was_sampled_from() -> None:
    assert prompts_by_edge() == {0: "prompt", 1: "prompt", 2: "feedback", 3: "feedback"}
