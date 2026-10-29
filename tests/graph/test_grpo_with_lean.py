import shutil
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
import pytest_asyncio
from tiny_models import CharacterTokenizer, save_tiny_model

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl, LeanReplConfig
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.policy.prompts import END_OF_TURN, normalized_block
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.policy_data import PolicyData, PolicyDataConfig, build_policy_data
from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    DepthPlusGoals,
    HarvestConfig,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    TreeRecord,
    search_theorem,
    tree_record,
)
from lean_search.search.graph_labels import label_graph
from lean_search.search.tactic_labels import TacticLabel, policy_tactics
from lean_search.search.texts import GeneratedText, SampledTokens, UnparsedSample

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
STATEMENT = "theorem squares (a b : ℕ) (h : a = b) : a * a = b * b := by\n"
PROMPT = "Prove it."
PROOF = "subst h\nrfl"
SAME_START_THEN_UNKNOWN = "subst h\nexact undefined_lemma"
REDUNDANT = "have h₂ : a = b := h"
NO_OP = "skip"
ERROR = "omega"
BLOCKS = (SAME_START_THEN_UNKNOWN, REDUNDANT, NO_OP, ERROR, PROOF)

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


def sampled_tokens(text: str) -> SampledTokens:
    """One token per character, ending with the end of turn, as the policy client records a sample."""
    token_ids = tuple(ord(character) for character in text + END_OF_TURN)
    return SampledTokens(token_ids, tuple(-0.25 for _ in token_ids))


class RecordingPolicy:
    """One request whose samples explain, then give a block; with token ids like vLLM's, and one unparsed sample."""

    def __init__(self, blocks: Sequence[str]) -> None:
        self.blocks = tuple(blocks)

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        candidates = []
        for block in self.blocks:
            text = f"Substitute, then close.\n\n```lean\n{block}\n```"
            positions = normalized_block(block, text.index(block)).positions
            generated = GeneratedText(text, True, positions, sampled_tokens(text))
            candidates.append(Candidate(block, StepSource.POLICY, log_probability=-1.0, completions=(generated,)))
        unparsed_text = "Thinking again and again"
        unparsed = (UnparsedSample(unparsed_text, False, "truncated", sampled_tokens(unparsed_text)),)
        yield CandidateBatch(tuple(candidates), prompt=PROMPT, unparsed=unparsed, temperature=0.8, top_p=1.0)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def record() -> AsyncIterator[TreeRecord]:
    async with LeanRepl(LeanReplConfig()) as repl:
        await repl.load_header(HEADER)
        config = SearchConfig(
            max_expansions=1, tactic_timeout_seconds=20.0, harvest=HarvestConfig(enabled=True, max_expansions=0)
        )
        problem = Problem("squares", Split.VALID, HEADER, STATEMENT, informal_prefix="", goal="")
        completed = await search_theorem(problem, repl, RecordingPolicy(BLOCKS), DepthPlusGoals(), config)
        assert completed.tree is not None
        yield tree_record(completed.tree, STATEMENT, completed.result)


def labels_of(record: TreeRecord, block: str) -> tuple[TacticLabel, ...]:
    (edge,) = [edge for edge in record.edges if edge.text == block]
    tactics = policy_tactics(record, label_graph(record), RewardConfig().off_graph_min_expanded_nodes)
    return tuple(outcome.label for outcome in tactics[edge.edge_id])


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (PROOF, (TacticLabel.PROOF_GRAPH, TacticLabel.PROOF_GRAPH)),
        (SAME_START_THEN_UNKNOWN, (TacticLabel.PROOF_GRAPH, TacticLabel.FAILING)),
        (REDUNDANT, (TacticLabel.REDUNDANT_HYPOTHESIS,)),
        (NO_OP, (TacticLabel.NO_PROGRESS,)),
        (ERROR, (TacticLabel.FAILING,)),
        ("", (TacticLabel.FAILING,)),
    ],
    ids=["proof", "same start then unknown name", "redundant", "no-op", "error", "unparsed"],
)
async def test_tactic_labels_from_a_real_search(record: TreeRecord, block: str, expected: tuple) -> None:
    assert labels_of(record, block) == expected


def policy_data(record: TreeRecord) -> PolicyData:
    labelled = label_phase_data([record], TrainingPhaseConfig())
    return build_policy_data(labelled.policy_trees, CharacterTokenizer(), PolicyDataConfig())


async def test_every_sample_of_the_root_group_is_a_sequence(record: TreeRecord) -> None:
    assert len(policy_data(record).sequences) == len(BLOCKS) + 1


async def test_recorded_tokens_decode_to_the_recorded_texts(record: TreeRecord) -> None:
    metrics = policy_data(record).metrics
    assert (metrics.token_mismatch_sequences, metrics.retokenized_sequences) == (0, 0)


async def test_the_failing_tactic_of_a_shared_start_is_pushed_down(record: TreeRecord) -> None:
    (sequence,) = [sequence for sequence in policy_data(record).sequences if sequence.edge_id == edge_id(record)]
    completion_text = "".join(
        chr(token) for token in sequence.tokenized.input_ids[sequence.tokenized.prompt_token_count :]
    )
    start = completion_text.index("subst h")
    failing = completion_text.index("exact undefined_lemma")
    assert sequence.advantages[start] > 0 > sequence.advantages[failing]


def edge_id(record: TreeRecord) -> int:
    (edge,) = [edge for edge in record.edges if edge.text == SAME_START_THEN_UNKNOWN]
    return edge.edge_id


async def test_one_trainer_step_on_a_tiny_model(record: TreeRecord, tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("peft")
    from lean_search.rl.policy_trainer import GrpoConfig, GrpoStepRecord, train_grpo
    from lean_search.training.sft import LoraSettings, OptimizationConfig

    model = save_tiny_model(tmp_path / "model")
    config = GrpoConfig(
        model=str(model),
        lora=LoraSettings(rank=8, alpha=8),
        optimization=OptimizationConfig(
            learning_rate=1e-3, warmup_fraction=0.0, micro_batch_tokens=8192, gradient_checkpointing=False
        ),
        passes_per_phase=1,
        scoring_micro_batch_tokens=8192,
    )
    steps: list[GrpoStepRecord] = []
    data = policy_data(record)
    result = train_grpo(config, 0, data.sequences, [], torch.device("cpu"), tmp_path / "adapter", steps.append)
    assert (len(steps), result.sampler_agreement.tokens > 0) == (1, True)


async def test_proof_tactic_states_were_recorded(record: TreeRecord) -> None:
    (edge,) = [edge for edge in record.edges if edge.text == PROOF]
    assert len(edge.tactic_goals) == 2 and edge.tactic_goals[-1] == ()
