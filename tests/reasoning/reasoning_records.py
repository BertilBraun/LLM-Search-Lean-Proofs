from collections.abc import Sequence

from lean_search.corpora.records import DataSplit, TracedStep
from lean_search.reasoning.records import BlockExecution, SampleRecord, StateRecord, StateSamples
from lean_search.reasoning.reward import StepOutcome
from lean_search.reasoning.states import ReasoningState, proof_states

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by"
GOALS = (
    ("a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5",),
    ("b : ℕ\nh₁ : b = 3\n⊢ 2 + b = 5",),
    ("⊢ 2 + 3 = 5",),
    (),
)
STEPS = ("subst h₀", "subst h₁", "norm_num")


def traced_step(
    index: int,
    source: str = "test",
    proof: str = "test/sum",
    split: DataSplit = DataSplit.TRAIN,
    goals: Sequence[tuple[str, ...]] = GOALS,
) -> TracedStep:
    return TracedStep(
        source=source,
        proof_identifier=proof,
        statement_identifier="sum",
        split=split,
        header=HEADER,
        formal_statement=STATEMENT,
        step_index=index,
        total_steps=len(STEPS),
        remaining_steps=len(STEPS) - index,
        goals_before=goals[index],
        step=STEPS[index],
        goals_after=goals[index + 1],
        previous_steps=STEPS[:index],
        heartbeats=200_000,
        elapsed_seconds=0.01,
    )


def proof_steps(source: str = "test", proof: str = "test/sum", split: DataSplit = DataSplit.TRAIN) -> list[TracedStep]:
    return [traced_step(index, source, proof, split) for index in range(len(STEPS))]


def first_state() -> ReasoningState:
    return proof_states(proof_steps())[0]


def thinking_text(reasoning: str, block: str) -> str:
    return f"{reasoning}\n</think>\n\n```lean\n{block}\n```"


def sample_record(
    index: int,
    block: str | None = "subst h₀",
    reasoning_tokens: int = 40,
    reasoning: str = "Substitute the value of a.",
    parse_failure: StepOutcome | None = None,
) -> SampleRecord:
    text = thinking_text(reasoning, block) if block is not None else reasoning
    return SampleRecord(
        index=index,
        text=text,
        finish_reason="length" if parse_failure == StepOutcome.TRUNCATED else "stop",
        generated_tokens=reasoning_tokens + 12,
        cumulative_logprob=-3.0,
        reasoning=reasoning,
        reasoning_tokens=reasoning_tokens,
        tactic_block=block,
        parse_failure=parse_failure,
    )


def execution(block: str, outcome: StepOutcome, advanced: int = 0) -> BlockExecution:
    return BlockExecution(
        tactic_block=block,
        outcome=outcome,
        reference_steps_advanced=advanced,
        applied_tactics=1,
        total_tactics=1,
        goals_after=(),
        lean_seconds=0.1,
        message="",
    )


def state_record(
    samples: Sequence[SampleRecord],
    executions: Sequence[BlockExecution],
    state: ReasoningState | None = None,
    start_failure: str = "",
) -> StateRecord:
    sampled = StateSamples(state or first_state(), True, 120, 100, 512, 1.0, tuple(samples))
    return StateRecord(sampled, start_failure, tuple(executions))
