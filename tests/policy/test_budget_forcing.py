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
    FENCE,
    THINK_END,
    answer_opening,
    forced_answer_prompt,
    forced_sample,
    parse_sample,
    parse_samples,
    truncated_in_thinking,
)
from lean_search.search import CandidateBatch, EdgeOutcome, SearchContext, SearchTree, StepSource
from lean_search.search.records import from_json_object, to_json
from lean_search.search.texts import GeneratedText, SampledTokens, TokenSpan
from lean_search.search.tree import Edge

PROMPT_TOKENS = 100
CUT_OFF_THOUGHTS = "The goal is linear, so I will try"


def sample(text: str, finish_reason: str = "stop", tokens: int = 5, log_probability: float = -1.0) -> Sample:
    return Sample(text=text, cumulative_logprob=log_probability, token_count=tokens, finish_reason=finish_reason)


def sampled(
    text: str, token_ids: tuple[int, ...], finish_reason: str = "stop", stop_string: str | None = None
) -> Sample:
    tokens = SampledTokens(token_ids, tuple(-0.5 for _ in token_ids))
    return Sample(text, -0.5 * len(token_ids), len(token_ids), finish_reason, tokens, stop_string)


def choice(
    text: str, finish_reason: str, tokens: int, first_token_id: int = 1000, stop_reason: str | None = None
) -> dict[str, object]:
    """A choice as vLLM's completions endpoint returns it with `logprobs: 0, return_tokens_as_token_ids: true`."""
    return {
        "text": text,
        "logprobs": {
            "tokens": [f"token_id:{first_token_id + offset}" for offset in range(tokens)],
            "token_logprobs": [-0.25] * tokens,
            "top_logprobs": [None] * tokens,
            "text_offset": list(range(tokens)),
        },
        "finish_reason": finish_reason,
        "stop_reason": stop_reason,
    }


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


@pytest.mark.parametrize(
    ("visible", "opening"),
    [(False, f"\n{THINK_END}\n\n{ASSISTANT_PREFILL}"), (True, f"\n\n{ASSISTANT_PREFILL}")],
)
def test_the_opening_closes_the_reasoning_and_opens_the_block(visible: bool, opening: str) -> None:
    assert answer_opening(visible=visible) == opening


def test_the_forced_prompt_is_the_prompt_the_cut_off_tokens_and_the_opening() -> None:
    prompt = forced_answer_prompt((1, 2), sampled(CUT_OFF_THOUGHTS, (3, 4), "length"), (5, 6))
    assert prompt == (1, 2, 3, 4, 5, 6)


def test_a_forced_sample_parses_to_the_continuations_block() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length", 1024), (), sample("linarith\n", "stop", 4))
    assert parse_sample(forced, thinking=True) == "linarith"


def test_a_forced_sample_charges_both_parts() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length", 1024, -30.0), (), sample("linarith", "stop", 4, -1.0))
    assert (forced.token_count, forced.cumulative_logprob) == (1028, -31.0)


def test_a_forced_answer_cut_off_again_stays_truncated() -> None:
    forced = forced_sample(sample(CUT_OFF_THOUGHTS, "length"), (), sample("nlinarith [sq_nonneg (a", "length", 256))
    assert parse_sample(forced, thinking=True) is not None and not isinstance(parse_sample(forced, thinking=True), str)


CUT_OFF = sampled(CUT_OFF_THOUGHTS, (11, 12, 13), "length")
OPENING_TOKEN_IDS = (21, 22)
FENCED_CONTINUATION = sampled("linarith\n", (31, 32), stop_string=FENCE)
CAPPED_CONTINUATION = sampled("nlinarith [sq_nonneg (a", (41, 42, 43), "length")


def test_a_forced_sample_keeps_every_token_the_model_saw() -> None:
    forced = forced_sample(CUT_OFF, OPENING_TOKEN_IDS, FENCED_CONTINUATION)
    assert forced.tokens.token_ids == (11, 12, 13, 21, 22, 31, 32)


def test_inserted_tokens_have_no_log_probability() -> None:
    forced = forced_sample(CUT_OFF, OPENING_TOKEN_IDS, FENCED_CONTINUATION)
    assert forced.tokens.log_probabilities == (-0.5, -0.5, -0.5, None, None, -0.5, -0.5)


def test_the_inserted_opening_is_marked_in_characters_and_tokens() -> None:
    forced = forced_sample(CUT_OFF, OPENING_TOKEN_IDS, FENCED_CONTINUATION)
    (opening,) = forced.tokens.inserted
    assert (forced.text[opening.characters.start : opening.characters.end], opening.tokens) == (
        f"\n{THINK_END}\n\n{ASSISTANT_PREFILL}",
        TokenSpan(3, 5),
    )


def test_a_closing_fence_the_model_wrote_is_not_marked_inserted() -> None:
    forced = forced_sample(CUT_OFF, OPENING_TOKEN_IDS, FENCED_CONTINUATION)
    assert (forced.text.endswith(f"linarith\n{FENCE}"), len(forced.tokens.inserted)) == (True, 1)


def test_a_closing_fence_added_after_the_cap_is_inserted_text_without_tokens() -> None:
    forced = forced_sample(CUT_OFF, OPENING_TOKEN_IDS, CAPPED_CONTINUATION)
    closing = forced.tokens.inserted[-1]
    assert (forced.text[closing.characters.start :], closing.tokens) == (f"\n{FENCE}", TokenSpan(8, 8))


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
        """One token per character, its code point."""
        return [ord(character) for character in text]


THINKING_RESPONSE = [
    choice(CUT_OFF_THOUGHTS, "length", 40, first_token_id=1000),
    choice(f"Close it.\n{THINK_END}\n\n```lean\nsimp\n```", "stop", 10, first_token_id=2000),
    choice(CUT_OFF_THOUGHTS + " again", "length", 40, first_token_id=3000),
]
FORCED_RESPONSE = [
    choice("linarith\n", "stop", 3, first_token_id=4000, stop_reason=FENCE),
    choice("nlinarith [sq_nonneg (a", "length", 30, first_token_id=5000),
]
THINKING_OPENING = [ord(character) for character in answer_opening(visible=False)]


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
    openings = [prompt[-len(THINKING_OPENING) :] for prompt in server.bodies[1]["prompt"]]
    assert openings == [THINKING_OPENING, THINKING_OPENING]


async def test_forced_requests_continue_the_cut_off_samples_own_tokens() -> None:
    server, _, _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    first_prompt = server.bodies[1]["prompt"][0]
    assert first_prompt[-len(THINKING_OPENING) - 40 : -len(THINKING_OPENING)] == list(range(1000, 1040))


async def test_requests_ask_for_sampled_token_ids() -> None:
    server, _, _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert [body["return_tokens_as_token_ids"] for body in server.bodies] == [True, True]


def completion_of(batch: CandidateBatch, text: str) -> GeneratedText:
    (candidate,) = (candidate for candidate in batch.candidates if candidate.text == text)
    (completion,) = candidate.completions
    return completion


async def test_samples_keep_their_token_ids_and_log_probabilities() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert completion_of(batch, "simp").tokens == SampledTokens(tuple(range(2000, 2010)), (-0.25,) * 10)


async def test_forced_samples_keep_the_cut_off_inserted_and_forced_tokens() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    token_ids = completion_of(batch, "linarith").tokens.token_ids
    assert token_ids == (*range(1000, 1040), *THINKING_OPENING, 4000, 4001, 4002)


async def test_forced_samples_mark_the_inserted_opening() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    completion = completion_of(batch, "linarith")
    (opening,) = completion.tokens.inserted
    assert completion.text[opening.characters.start : opening.characters.end] == answer_opening(visible=False)


async def test_the_batch_records_the_sampling_settings() -> None:
    _, (batch,), _ = await expand(THINKING, [THINKING_RESPONSE, FORCED_RESPONSE])
    assert (batch.temperature, batch.top_p) == (THINKING.temperature, THINKING.top_p)


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
        [[ord(character) for character in "\n\n```lean\n"]],
    )


async def test_visible_forced_blocks_become_marked_candidates() -> None:
    _, (batch,), _ = await expand(VISIBLE, [VISIBLE_RESPONSE, [choice("linarith\n", "stop", 3)]])
    assert sorted((candidate.text, candidate.forced) for candidate in batch.candidates) == [
        ("linarith", True),
        ("simp", False),
    ]
