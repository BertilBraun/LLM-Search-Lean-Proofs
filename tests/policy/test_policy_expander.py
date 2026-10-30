import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl, ProofState
from lean_search.policy import PolicyClient, Sample
from lean_search.policy.client import Generation
from lean_search.policy.config import FeedbackConfig, PolicyConfig
from lean_search.policy.expander import PolicyExpander, candidate_batch, failed_attempt, failed_blocks
from lean_search.policy.prompts import BRIEF_THINKING_INSTRUCTION, parse_samples
from lean_search.search import (
    CandidateBatch,
    Edge,
    EdgeOutcome,
    ExpanderKind,
    Failure,
    FailureKind,
    SearchContext,
    SearchTree,
    StepSource,
)
from lean_search.search.config import parse_run_config
from lean_search.search.texts import SampledTokens

POLICY_SECTION = """
[expander]
kind = "automation_then_policy"

[policy]
model = "qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
"""
TWO_SERVERS = 'server_urls = ["http://127.0.0.1:8000/v1", "http://127.0.0.1:8001/v1"]\n'
PROMPT_TOKENS = 100
TRUNCATED_CHOICE = {
    "text": "simp [",
    "logprobs": {"tokens": ["token_id:3"] * 6, "token_logprobs": [-0.5] * 6},
    "finish_reason": "length",
}


def parsed_samples() -> list[Sample]:
    return [
        Sample("simp", cumulative_logprob=-2.0, token_count=3, finish_reason="stop"),
        Sample("sorry", cumulative_logprob=-1.0, token_count=4, finish_reason="stop"),
        Sample("omega", cumulative_logprob=-1.5, token_count=2, finish_reason="stop"),
    ]


def generation(samples: list[Sample]) -> Generation:
    return Generation(samples, PROMPT_TOKENS, 0, sum(sample.token_count for sample in samples))


def batch_of(samples: list[Sample]) -> CandidateBatch:
    return candidate_batch(parse_samples(samples, thinking=False), generation(samples))


def test_batch_charges_the_prompt_and_every_sample() -> None:
    batch = batch_of(parsed_samples())
    assert (batch.prompt_tokens, batch.generated_tokens) == (PROMPT_TOKENS, 3 + 4 + 2)


def test_request_whose_samples_all_failed_is_a_charged_empty_batch() -> None:
    truncated = [Sample("simp [", cumulative_logprob=-1.0, token_count=7, finish_reason="length")] * 2
    batch = batch_of(truncated)
    assert (batch.candidates, batch.prompt_tokens, batch.generated_tokens) == ((), PROMPT_TOKENS, 14)


def test_each_candidate_logs_the_prompt_and_its_own_samples() -> None:
    candidates = batch_of(parsed_samples()).candidates
    assert [(candidate.text, candidate.prompt_tokens, candidate.generated_tokens) for candidate in candidates] == [
        ("omega", PROMPT_TOKENS, 2),
        ("simp", PROMPT_TOKENS, 3),
    ]


def test_candidates_carry_their_log_probability() -> None:
    candidates = batch_of(parsed_samples()).candidates
    assert [candidate.log_probability for candidate in candidates] == [-1.5, -2.0]


VISIBLE_SAMPLES = [
    Sample("Simplify.\n\n```lean\nsimp\n```", cumulative_logprob=-1.0, token_count=5, finish_reason="stop"),
    Sample("Again.\n```lean\n  simp\n```", cumulative_logprob=-2.0, token_count=5, finish_reason="stop"),
    Sample("Loop, loop, loop", cumulative_logprob=-9.0, token_count=9, finish_reason="length"),
]


def visible_batch() -> CandidateBatch:
    parsed = parse_samples(VISIBLE_SAMPLES, thinking=False, visible=True)
    return candidate_batch(parsed, generation(VISIBLE_SAMPLES), prompt="<prompt>")


def test_merged_candidate_keeps_every_sample_text() -> None:
    (candidate,) = visible_batch().candidates
    assert [completion.text for completion in candidate.completions] == [sample.text for sample in VISIBLE_SAMPLES[:2]]


def test_block_positions_point_into_each_sample_text() -> None:
    (candidate,) = visible_batch().candidates
    spans = [
        completion.text[completion.block_positions[0] : completion.block_positions[-1]]
        for completion in candidate.completions
    ]
    assert spans == ["simp", "simp"]


def test_unparsed_samples_are_passed_on_with_their_reason() -> None:
    assert [(sample.text, sample.reason) for sample in visible_batch().unparsed] == [("Loop, loop, loop", "truncated")]


def test_recorded_log_probabilities_are_rounded() -> None:
    tokens = SampledTokens((5, 6), (-0.123456, -2.5e-07))
    samples = [Sample("simp", cumulative_logprob=-0.12, token_count=2, finish_reason="stop", tokens=tokens)]
    (candidate,) = batch_of(samples).candidates
    assert candidate.completions[0].tokens.log_probabilities == (-0.1235, -0.0)


def test_truncated_sample_did_not_end_its_turn() -> None:
    assert not visible_batch().unparsed[0].ended_turn


def test_batch_carries_the_prompt() -> None:
    assert visible_batch().prompt == "<prompt>"


class PlainTemplate:
    """Stands in for a Hugging Face tokenizer: the messages' contents joined, one token per word."""

    def apply_chat_template(
        self,
        conversation: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
        enable_thinking: bool,
    ) -> str:
        return "\n\n".join(message["content"] for message in conversation)

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [0] * len(text.split())


@dataclass
class CompletionServer:
    """Answers every completion request with the same choices and keeps the prompts it was sent."""

    choices: list[dict[str, object]]
    prompts: list[str] = field(default_factory=list)
    sample_counts: list[int] = field(default_factory=list)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers = await reader.readuntil(b"\r\n\r\n")
        length = next(
            int(line.split(b":")[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length")
        )
        body = json.loads(await reader.readexactly(length))
        self.prompts.append(body["prompt"])
        self.sample_counts.append(body["n"])
        choices = [{"index": index, **choice} for index, choice in enumerate(self.choices)]
        completion_tokens = sum(len(choice["logprobs"]["token_logprobs"]) for choice in self.choices)
        usage = {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": completion_tokens}
        body = json.dumps({"choices": choices, "usage": usage}).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()


@contextlib.asynccontextmanager
async def completion_server(choices: list[dict[str, object]]) -> AsyncIterator[tuple[CompletionServer, str]]:
    state = CompletionServer(choices)
    server = await asyncio.start_server(state.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield state, f"http://127.0.0.1:{port}/v1"


async def expand_root(server_url: str, config: PolicyConfig) -> list[CandidateBatch]:
    state = ProofState("", "theorem t : True := by\n", (), ("⊢ True",), 0, 0)
    tree = SearchTree("t", state, 0.0)
    context = SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())
    async with PolicyClient(server_url, config.model) as client:
        expander = PolicyExpander(config, PlainTemplate(), [client], max_model_length=4096)
        return [batch async for batch in expander.expand(tree.root, context)]


async def test_expander_yields_a_request_whose_samples_all_failed() -> None:
    async with completion_server([TRUNCATED_CHOICE, TRUNCATED_CHOICE]) as (_, url):
        batches = await expand_root(url, PolicyConfig(model="policy", sample_count=2))
    assert [(batch.candidates, batch.generated_tokens) for batch in batches] == [((), 12)]


@pytest.mark.parametrize("thinking", [True, False])
async def test_thinking_instruction_reaches_the_prompt_only_when_thinking(thinking: bool) -> None:
    config = PolicyConfig(model="policy", thinking=thinking, thinking_instruction=BRIEF_THINKING_INSTRUCTION)
    async with completion_server([TRUNCATED_CHOICE]) as (server, url):
        await expand_root(url, config)
    assert (BRIEF_THINKING_INSTRUCTION in server.prompts[0]) == thinking


def test_policy_section_is_parsed() -> None:
    config = parse_run_config(POLICY_SECTION + TWO_SERVERS)
    assert (config.expander.kind, config.policy.server_urls, config.policy.adapter) == (
        ExpanderKind.AUTOMATION_THEN_POLICY,
        ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8001/v1"),
        None,
    )


def test_thinking_instruction_is_parsed() -> None:
    config = parse_run_config(
        POLICY_SECTION + f'thinking = true\nthinking_instruction = "{BRIEF_THINKING_INSTRUCTION}"\n'
    )
    assert config.policy.thinking_instruction == BRIEF_THINKING_INSTRUCTION


def test_policy_defaults_to_non_thinking_few_shot() -> None:
    assert (PolicyConfig().thinking, PolicyConfig().few_shot) == (False, True)


def test_policy_defaults_to_no_thinking_instruction() -> None:
    assert PolicyConfig().thinking_instruction == ""


@pytest.mark.parametrize("kind", [ExpanderKind.POLICY, ExpanderKind.AUTOMATION_THEN_POLICY])
def test_policy_kinds_need_a_model(kind: ExpanderKind) -> None:
    with pytest.raises(ValueError):
        parse_run_config(f'[expander]\nkind = "{kind}"\n')


@pytest.mark.parametrize(
    "policy",
    ["sample_count = 0\n", "server_urls = []\n", 'temperature = "hot"\n', 'thinking_instruction = "Be brief."\n'],
)
def test_invalid_policy_section_is_rejected(policy: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(POLICY_SECTION + policy)


LINARITH = Failure(FailureKind.ERROR, "linarith failed to find a contradiction")
FEEDBACK = PolicyConfig(model="policy", sample_count=2, feedback=FeedbackConfig(enabled=True, sample_count=3))
SWEEP_POLICY = '[policy]\nmodel = "m"\ntokenizer = "t"\nfailed_automation_in_prompt = true\n'


def choice(text: str) -> dict[str, object]:
    return {"text": text, "logprobs": {"tokens": ["token_id:3"], "token_logprobs": [-0.5]}, "finish_reason": "stop"}


def root_context() -> SearchContext:
    state = ProofState("", "theorem t : True := by\n", (), ("⊢ True",), 0, 0)
    tree = SearchTree("t", state, 0.0)
    tree.root.expansion_index = 0
    return SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())


async def expand_as_the_search(
    server_url: str, config: PolicyConfig, outcome: EdgeOutcome, context: SearchContext | None = None
) -> list[CandidateBatch]:
    """Every batch's candidates enter the tree with `outcome` (failing with LINARITH) before the next is asked for."""
    context = context or root_context()
    tree = context.tree
    batches = []
    async with PolicyClient(server_url, config.model) as client:
        expander = PolicyExpander(config, PlainTemplate(), [client], max_model_length=4096)
        async with contextlib.aclosing(expander.expand(tree.root, context)) as generator:
            async for batch in generator:
                batches.append(batch)
                for candidate in batch.candidates:
                    tree.add_edge(
                        tree.root,
                        text=candidate.text,
                        source=StepSource.POLICY,
                        log_probability=candidate.log_probability,
                        prompt_tokens=0,
                        generated_tokens=0,
                        outcome=outcome,
                        target_id=tree.next_node_id() if outcome == EdgeOutcome.CHILD else None,
                        failure=LINARITH if outcome == EdgeOutcome.FAILED else None,
                        feedback=candidate.feedback,
                    )
    return batches


async def test_samples_without_new_states_get_a_feedback_round() -> None:
    async with completion_server([choice("nlinarith"), choice("simp")]) as (_, url):
        batches = await expand_as_the_search(url, FEEDBACK, EdgeOutcome.FAILED)
    assert [batch.feedback for batch in batches] == [False, True]


async def test_feedback_candidates_are_marked() -> None:
    async with completion_server([choice("nlinarith"), choice("simp")]) as (_, url):
        batches = await expand_as_the_search(url, FEEDBACK, EdgeOutcome.FAILED)
    assert all(candidate.feedback for candidate in batches[1].candidates)


async def test_feedback_prompt_shows_the_failed_block_and_its_error() -> None:
    async with completion_server([choice("nlinarith")]) as (server, url):
        await expand_as_the_search(url, FEEDBACK, EdgeOutcome.FAILED)
    assert "```lean\nnlinarith\n```\nError: linarith failed to find a contradiction" in server.prompts[1]


async def test_feedback_round_samples_its_own_count() -> None:
    async with completion_server([choice("nlinarith")]) as (server, url):
        await expand_as_the_search(url, FEEDBACK, EdgeOutcome.FAILED)
    assert server.sample_counts == [2, 3]


async def test_enough_new_states_need_no_feedback_round() -> None:
    async with completion_server([choice("nlinarith"), choice("simp")]) as (_, url):
        batches = await expand_as_the_search(url, FEEDBACK, EdgeOutcome.CHILD)
    assert len(batches) == 1


async def test_samples_reaching_existing_states_give_no_errors_to_show() -> None:
    async with completion_server([choice("nlinarith"), choice("simp")]) as (_, url):
        batches = await expand_as_the_search(url, FEEDBACK, EdgeOutcome.DUPLICATE)
    assert len(batches) == 1


async def test_feedback_is_off_by_default() -> None:
    async with completion_server([choice("nlinarith")]) as (_, url):
        batches = await expand_as_the_search(url, PolicyConfig(model="policy", sample_count=2), EdgeOutcome.FAILED)
    assert len(batches) == 1


async def test_prompt_names_the_automation_that_failed_at_the_node() -> None:
    context = root_context()
    sweep = [("omega", EdgeOutcome.FAILED), ("ring_nf", EdgeOutcome.DUPLICATE), ("simp_all", EdgeOutcome.FAILED)]
    for tactic, outcome in sweep:
        context.tree.add_edge(
            context.tree.root,
            text=tactic,
            source=StepSource.AUTOMATION,
            log_probability=None,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=outcome,
        )
    config = PolicyConfig(model="policy", sample_count=1, failed_automation_in_prompt=True)
    async with completion_server([choice("nlinarith")]) as (server, url):
        await expand_as_the_search(url, config, EdgeOutcome.CHILD, context)
    assert "Already tried here without success: omega, simp_all" in server.prompts[0]


@pytest.mark.parametrize(
    "expander", ['[expander]\nkind = "automation_then_policy"\noverlap = true\n', '[expander]\nkind = "policy"\n']
)
def test_failed_automation_in_the_prompt_needs_the_sweep_to_finish_first(expander: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(expander + SWEEP_POLICY)


def test_failed_automation_in_the_prompt_runs_after_a_finished_sweep() -> None:
    config = parse_run_config('[expander]\nkind = "automation_then_policy"\n' + SWEEP_POLICY)
    assert config.policy.failed_automation_in_prompt


@pytest.mark.parametrize("feedback", ["min_children = 0", "sample_count = 0", "max_error_characters = 4"])
def test_invalid_feedback_section_is_rejected(feedback: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(POLICY_SECTION + f"[policy.feedback]\nenabled = true\n{feedback}\n")


BLIND = PolicyConfig(
    model="policy", sample_count=2, feedback=FeedbackConfig(enabled=True, sample_count=3, show_attempts=False)
)


async def test_blind_feedback_round_repeats_the_node_s_own_prompt() -> None:
    async with completion_server([choice("nlinarith")]) as (server, url):
        await expand_as_the_search(url, BLIND, EdgeOutcome.FAILED)
    assert server.prompts[1] == server.prompts[0]


async def test_blind_feedback_round_is_marked_feedback() -> None:
    async with completion_server([choice("nlinarith")]) as (_, url):
        batches = await expand_as_the_search(url, BLIND, EdgeOutcome.FAILED)
    assert [batch.feedback for batch in batches] == [False, True]


async def test_no_feedback_round_at_a_node_already_proved() -> None:
    context = root_context()
    tree = context.tree
    edge = tree.add_edge(
        tree.root,
        text="decide",
        source=StepSource.AUTOMATION,
        log_probability=None,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.CHILD,
        target_id=tree.next_node_id(),
        applied_tactics=1,
        total_tactics=1,
    )
    proved = ProofState("", tree.root.state.statement, ("decide",), (), 0, 0)
    tree.add_child(tree.root, edge.edge_id, "decide", StepSource.AUTOMATION, None, proved, 0.0, 0.0)
    async with completion_server([choice("nlinarith")]) as (_, url):
        batches = await expand_as_the_search(url, FEEDBACK, EdgeOutcome.FAILED, context)
    assert len(batches) == 1


def root_edge(tree: SearchTree, text: str, outcome: EdgeOutcome, source: StepSource = StepSource.POLICY) -> Edge:
    return tree.add_edge(
        tree.root,
        text=text,
        source=source,
        log_probability=-1.0,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=outcome,
        target_id=tree.next_node_id() if outcome == EdgeOutcome.CHILD else None,
        failure=LINARITH,
    )


def test_block_that_made_progress_before_failing_is_no_failed_attempt() -> None:
    tree = root_context().tree
    edges = [
        root_edge(tree, "constructor\nlinarith", EdgeOutcome.CHILD),
        root_edge(tree, "nlinarith", EdgeOutcome.FAILED),
    ]
    assert [edge.text for edge in failed_blocks(edges)] == ["nlinarith"]


def test_repair_is_no_failed_attempt() -> None:
    tree = root_context().tree
    assert failed_blocks([root_edge(tree, "rw [Nat.add_zero]", EdgeOutcome.FAILED, StepSource.REPAIR)]) == []


def test_failed_attempt_shows_the_error_s_first_line() -> None:
    tree = root_context().tree
    edge = tree.add_edge(
        tree.root,
        text="nlinarith",
        source=StepSource.POLICY,
        log_probability=-1.0,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.FAILED,
        failure=Failure(FailureKind.ERROR, "linarith failed to find a contradiction\ncase a\nx : ℝ\n⊢ False failed"),
    )
    assert failed_attempt(edge, FeedbackConfig()).error == "linarith failed to find a contradiction"
