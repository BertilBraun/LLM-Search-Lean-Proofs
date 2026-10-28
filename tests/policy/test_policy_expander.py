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
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyExpander, candidate_batch
from lean_search.policy.prompts import BRIEF_THINKING_INSTRUCTION, parse_samples
from lean_search.search import CandidateBatch, ExpanderKind, SearchContext, SearchTree
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

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers = await reader.readuntil(b"\r\n\r\n")
        length = next(
            int(line.split(b":")[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length")
        )
        self.prompts.append(json.loads(await reader.readexactly(length))["prompt"])
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
