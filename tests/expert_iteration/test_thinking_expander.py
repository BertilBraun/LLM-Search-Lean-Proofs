from collections.abc import Sequence
from dataclasses import dataclass, field

from lean_search.data import Problem, Split
from lean_search.expert_iteration.thinking_expander import ReasoningExpander, ReasoningLog
from lean_search.lean import LeanRepl, ProofState
from lean_search.policy.client import Generation, Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyExpander
from lean_search.policy.prompts import THINK_END
from lean_search.search import CandidateBatch, SearchContext, SearchTree

CUT_OFF_THOUGHTS = "The goal is linear, so I will try"
FINISHED = Sample(f"Close it.\n{THINK_END}\n\n```lean\nsimp\n```", -2.0, 10, "stop")
CUT_OFF = Sample(CUT_OFF_THOUGHTS, -30.0, 40, "length")
FORCED_ANSWER = Sample("linarith\n", -1.0, 3, "stop")


@dataclass
class ScriptedClient:
    """Answers the sampling request with fixed samples and every forcing prompt with a fixed block."""

    samples: list[Sample]
    forced_prompts: list[str] = field(default_factory=list)

    async def generate(self, prompt: str, **_: object) -> Generation:
        return Generation(self.samples, 100, 0, sum(sample.token_count for sample in self.samples))

    async def generate_each(self, prompts: Sequence[str], **_: object) -> Generation:
        self.forced_prompts.extend(prompts)
        return Generation([FORCED_ANSWER] * len(prompts), 100, 0, FORCED_ANSWER.token_count * len(prompts))


class PlainTemplate:
    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        return "\n\n".join(message["content"] for message in conversation)

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [0] * len(text.split())


async def expand(config: PolicyConfig) -> tuple[list[CandidateBatch], ReasoningLog, PolicyExpander]:
    state = ProofState("", "theorem t : True := by\n", (), ("⊢ True",), 0, 0)
    tree = SearchTree("t", state, 0.0)
    context = SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())
    inner = PolicyExpander(config, PlainTemplate(), [ScriptedClient([FINISHED, CUT_OFF])], max_model_length=4096)
    log = ReasoningLog()
    batches = [batch async for batch in ReasoningExpander(inner, log).expand(tree.root, context)]
    return batches, log, inner


THINKING = PolicyConfig(model="policy", thinking=True, sample_count=2, max_tokens=40)


async def test_a_cut_off_thought_still_gives_a_forced_candidate() -> None:
    (batch,), _, _ = await expand(THINKING)
    assert sorted((candidate.text, candidate.forced) for candidate in batch.candidates) == [
        ("linarith", True),
        ("simp", False),
    ]


async def test_a_forced_block_keeps_its_cut_off_reasoning() -> None:
    _, log, _ = await expand(THINKING)
    reasoning = {entry.step: entry.reasoning for entry in log.take("t")}
    assert reasoning["linarith"] == CUT_OFF_THOUGHTS


async def test_forcing_is_counted_in_the_policy_statistics() -> None:
    _, _, inner = await expand(THINKING)
    assert (inner.statistics.forced_samples, inner.statistics.forced_blocks) == (1, 1)


async def test_without_forcing_a_cut_off_thought_gives_nothing() -> None:
    config = PolicyConfig(
        model="policy", thinking=True, sample_count=2, max_tokens=40, force_answer_on_truncation=False
    )
    (batch,), _, _ = await expand(config)
    assert [candidate.text for candidate in batch.candidates] == ["simp"]
