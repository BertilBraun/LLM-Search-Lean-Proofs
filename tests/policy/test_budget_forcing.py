import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl, ProofState
from lean_search.policy import PolicyClient, Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyExpander
from lean_search.policy.prompts import (
    ASSISTANT_PREFILL,
    THINK_END,
    forced_answer_prompt,
    forced_sample,
    parse_sample,
    parse_samples,
    truncated_in_thinking,
)
from lean_search.search import CandidateBatch, EdgeOutcome, SearchContext, SearchTree, StepSource
from lean_search.search.records import from_json_object, to_json
from lean_search.search.tree import Edge

PROMPT_TOKENS = 100
CUT_OFF_THOUGHTS = "The goal is linear, so I will try"


def sample(text: str, finish_reason: str = "stop", tokens: int = 5, log_probability: float = -1.0) -> Sample:
    return Sample(text=text, cumulative_logprob=log_probability, token_count=tokens, finish_reason=finish_reason)


def choice(text: str, finish_reason: str, tokens: int) -> dict[str, object]:
    return {"text": text, "logprobs": {"token_logprobs": [-0.25] * tokens}, "finish_reason": finish_reason}


@pytest.mark.parametrize(
    ("text", "finish_reason", "truncated"),
    [
        (CUT_OFF_THOUGHTS, "length", True),
        (f"Linear.\n{THINK_END}\n\n```lean\nlinar", "length", False),
        (f"Linear.\n{THINK_END}\n\n```lean\nlinarith\n```", "stop", False),
    ],
)
def test_only_samples_cut_off_inside_their_thoughts_are_forced(text: str, finish_reason: str, truncated: bool) -> None:
    assert truncated_in_thinking(sample(text, finish_reason)) == truncated


def test_the_forced_prompt_closes_the_thoughts_and_opens_the_block() -> None:
    prompt = forced_answer_prompt("<prompt>", sample(CUT_OFF_THOUGHTS, "length"))
    assert prompt == f"<prompt>{CUT_OFF_THOUGHTS}\n{THINK_END}\n\n{ASSISTANT_PREFILL}"


def test_a_forced_sample_parses_to_the_continuations_block() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length", 1024), sample("linarith\n", "stop", 4))
    assert parse_sample(forced, thinking=True) == "linarith"


def test_a_forced_sample_charges_both_parts() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length", 1024, -30.0), sample("linarith", "stop", 4, -1.0))
    assert (forced.token_count, forced.cumulative_logprob) == (1028, -31.0)


def test_a_forced_answer_cut_off_again_stays_truncated() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length"), sample("nlinarith [sq_nonneg (a", "length", 256))
    assert parse_sample(forced, thinking=True) is not None and not isinstance(parse_sample(forced, thinking=True), str)


@pytest.mark.parametrize(("forced_indices", "forced"), [(frozenset({0}), True), (frozenset(), False)])
def test_candidates_from_forced_samples_are_marked(forced_indices: frozenset[int], forced: bool) -> None:
    samples = [sample(f"x\n{THINK_END}\n\n```lean\nomega\n```")]
    (candidate,) = parse_samples(samples, thinking=True, forced_indices=forced_indices).candidates
    assert candidate.forced == forced


def test_a_block_also_written_without_forcing_is_not_forced() -> None:
    samples = [sample(f"x\n{THINK_END}\n\n```lean\nomega\n```")] * 2
    (candidate,) = parse_samples(samples, thinking=True, forced_indices=frozenset({0})).candidates
    assert (candidate.forced, candidate.forced_sample_count) == (False, 1)


@dataclass
class SequencedServer:
    """Answers the n-th completion request with the n-th list of choices and keeps every request body."""

    responses: list[list[dict[str, object]]]
    bodies: list[dict[str, object]] = field(default_factory=list)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers = await reader.readuntil(b"\r\n\r\n")
        length = next(
            int(line.split(b":")[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length")
        )
        self.bodies.append(json.loads(await reader.readexactly(length)))
        choices = self.responses[len(self.bodies) - 1]
        indexed = [{"index": index, **entry} for index, entry in enumerate(choices)]
        completion_tokens = sum(len(entry["logprobs"]["token_logprobs"]) for entry in choices)
        usage = {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": completion_tokens}
        body = json.dumps({"choices": indexed, "usage": usage}).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()


@contextlib.asynccontextmanager
async def sequenced_server(responses: list[list[dict[str, object]]]) -> AsyncIterator[tuple[SequencedServer, str]]:
    state = SequencedServer(responses)
    server = await asyncio.start_server(state.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield state, f"http://127.0.0.1:{port}/v1"


class PlainTemplate:
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


THINKING_RESPONSE = [
    choice(CUT_OFF_THOUGHTS, "length", 40),
    choice(f"Close it.\n{THINK_END}\n\n```lean\nsimp\n```", "stop", 10),
    choice(CUT_OFF_THOUGHTS + " again", "length", 40),
]
FORCED_RESPONSE = [choice("linarith\n", "stop", 3), choice("nlinarith [sq_nonneg (a", "length", 30)]


async def expand(
    config: PolicyConfig, responses: list[list[dict[str, object]]]
) -> tuple[SequencedServer, list[CandidateBatch], PolicyExpander]:
    state = ProofState("", "theorem t : True := by\n", (), ("⊢ True",), 0, 0)
    tree = SearchTree("t", state, 0.0)
    context = SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())
    async with sequenced_server(responses) as (server, url), PolicyClient(url, config.model) as client:
        expander = PolicyExpander(config, PlainTemplate(), [client], max_model_length=4096)
        batches = [batch async for batch in expander.expand(tree.root, context)]
    return server, batches, expander


THINKING = PolicyConfig(model="policy", thinking=True, sample_count=3, max_tokens=40)


async def test_one_forcing_request_carries_every_cut_off_sample() -> None:
    server, _, _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    prompts = server.bodies[1]["prompt"]
    assert (len(server.bodies), len(prompts), server.bodies[1]["stop"]) == (2, 2, ["```"])


async def test_forced_requests_open_the_block_after_the_closed_thoughts() -> None:
    server, _, _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert all(prompt.endswith(f"{THINK_END}\n\n{ASSISTANT_PREFILL}") for prompt in server.bodies[1]["prompt"])


async def test_forced_blocks_become_marked_candidates() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert sorted((candidate.text, candidate.forced) for candidate in batch.candidates) == [
        ("linarith", True),
        ("simp", False),
    ]


async def test_the_batch_charges_the_forcing_request() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert (batch.prompt_tokens, batch.generated_tokens) == (2 * PROMPT_TOKENS, 40 + 10 + 40 + 3 + 30)


async def test_forcing_statistics_count_attempts_and_usable_blocks() -> None:
    _, _, expander = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    statistics = expander.statistics
    assert (statistics.forced_samples, statistics.forced_blocks, statistics.forced_generated_tokens) == (2, 1, 33)


async def test_forcing_can_be_turned_off() -> None:
    config = PolicyConfig(
        model="policy", thinking=True, sample_count=3, max_tokens=40, force_answer_on_truncation=False
    )
    server, (batch,), _ = await expand(config, [THINKING_RESPONSE])
    assert (len(server.bodies), [candidate.text for candidate in batch.candidates]) == (1, ["simp"])


def test_forcing_is_on_by_default() -> None:
    assert PolicyConfig().force_answer_on_truncation


def test_edges_without_a_forced_field_read_as_unforced() -> None:
    edge = Edge(0, 0, 0, "simp", StepSource.POLICY, -1.0, 10, 3, EdgeOutcome.CHILD, 1, 1, 1, None, 0.1, None)
    record = json.loads(to_json(edge))
    del record["forced"]
    assert not from_json_object(Edge, record).forced


VISIBLE = PolicyConfig(model="policy", visible_reasoning=True, few_shot=False, sample_count=2, max_tokens=40)
VISIBLE_RESPONSE = [
    choice("Both sides are linear in x, so", "length", 40),
    choice("Close it with simp.\n\n```lean\nsimp\n```", "stop", 10),
]


async def test_visible_reasoning_forces_samples_cut_off_before_their_block() -> None:
    server, (batch,), _ = await expand(VISIBLE, [VISIBLE_RESPONSE, [choice("linarith\n", "stop", 3)]])
    assert (server.bodies[0]["stop"], [prompt[-10:] for prompt in server.bodies[1]["prompt"]]) == (
        [],
        ["\n\n```lean\n"],
    )


async def test_visible_forced_blocks_become_marked_candidates() -> None:
    _, (batch,), _ = await expand(VISIBLE, [VISIBLE_RESPONSE, [choice("linarith\n", "stop", 3)]])
    assert sorted((candidate.text, candidate.forced) for candidate in batch.candidates) == [
        ("linarith", True),
        ("simp", False),
    ]
