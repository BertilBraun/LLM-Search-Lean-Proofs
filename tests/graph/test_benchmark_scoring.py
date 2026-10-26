import json
import math
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tiny_models import DEAD_TOKEN, CharacterTokenizer

from lean_search.policy.client import TOKEN_ID_PREFIX, PolicyClient
from lean_search.search.graph_labels import NodeClass
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkGroup,
    BenchmarkScores,
    BenchmarkState,
    SearchGuidance,
    TreeProvenance,
    ValueBenchmark,
    benchmark_metrics,
    fresh_estimates,
)
from lean_search.value.benchmark_scoring import score_benchmark
from lean_search.value.bins import Readout
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import ValueModelEstimator

BIN_TOKEN_IDS = (*(ord(str(steps)) for steps in range(1, 9)), DEAD_TOKEN)
# Top-k logprobs as vLLM returns them per prompt: a dead end, a one-step state, and the "8" bin missing from the top k.
DEAD_LOGPROBS = {DEAD_TOKEN: math.log(0.6), ord("1"): math.log(0.2), ord("x"): math.log(0.1)}
ONE_STEP_LOGPROBS = {ord("1"): math.log(0.7), ord("2"): math.log(0.2), DEAD_TOKEN: math.log(0.05)}
MAX_MODEL_LENGTH = 400


def completion_response(prompts: list[str]) -> dict[str, object]:
    """A vLLM /v1/completions answer with max_tokens 1, logprobs and return_tokens_as_token_ids."""
    choices = []
    for index, prompt in enumerate(prompts):
        logprobs = DEAD_LOGPROBS if "dead" in prompt.split("Proof state")[-1] else ONE_STEP_LOGPROBS
        top = {f"{TOKEN_ID_PREFIX}{token_id}": logprob for token_id, logprob in logprobs.items()}
        choices.append({"index": index, "text": "", "logprobs": {"top_logprobs": [top]}})
    return {"choices": list(reversed(choices)), "usage": {"prompt_tokens": sum(len(prompt) for prompt in prompts)}}


class CompletionHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["max_tokens"] == 1 and body["model"] == "value-test"
        payload = json.dumps(completion_response(body["prompt"])).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *arguments: object) -> None:
        pass


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture
async def estimator(server_url: str) -> AsyncIterator[ValueModelEstimator]:
    config = ValueConfig(model="base", tokenizer="unused", server_urls=(server_url,), adapter="value-test")
    async with PolicyClient(server_url, "base") as client:
        yield ValueModelEstimator(config, CharacterTokenizer(), [client], MAX_MODEL_LENGTH)


def benchmark() -> ValueBenchmark:
    provenance = TreeProvenance("row2", SearchGuidance.VALUE_FREE, None, "")
    states = (
        BenchmarkState("row2", "t", 1, ("⊢ p",), NodeClass.PROOF_GRAPH, 1.0, 1, 1),
        BenchmarkState("row2", "t", 2, ("⊢ dead",), NodeClass.DEAD_END, 0.0, None, 1),
        BenchmarkState("row2", "t", 3, ("⊢ " + "l" * MAX_MODEL_LENGTH,), NodeClass.NEVER_EXPANDED, None, None, 0),
    )
    return ValueBenchmark((provenance,), states, (BenchmarkGroup("row2", "t", 0, (0, 1, 2)),))


def renormalized(logprobs: dict[int, float]) -> list[float]:
    floor = min(logprobs.values())
    weights = [math.exp(logprobs.get(token_id, floor)) for token_id in BIN_TOKEN_IDS]
    return [weight / sum(weights) for weight in weights]


async def test_served_scores_are_the_bin_tokens_renormalized(estimator: ValueModelEstimator) -> None:
    scores = await score_benchmark(estimator, benchmark())
    assert scores.distributions[0] == pytest.approx(renormalized(ONE_STEP_LOGPROBS))


async def test_responses_are_matched_to_their_states(estimator: ValueModelEstimator) -> None:
    scores = await score_benchmark(estimator, benchmark())
    assert scores.distributions[1] == pytest.approx(renormalized(DEAD_LOGPROBS))


async def test_a_state_too_long_for_the_server_gets_no_score(estimator: ValueModelEstimator) -> None:
    assert (await score_benchmark(estimator, benchmark())).distributions[2] is None


async def test_scores_carry_the_served_model_name(estimator: ValueModelEstimator) -> None:
    assert (await score_benchmark(estimator, benchmark())).model == "value-test"


async def test_served_scores_feed_the_benchmark_metrics(estimator: ValueModelEstimator) -> None:
    scores: BenchmarkScores = await score_benchmark(estimator, benchmark())
    metrics = benchmark_metrics(benchmark(), fresh_estimates(benchmark(), scores, Readout()), BenchmarkConfig())
    assert (metrics.ranking.proof_over_dead_end.accuracy, metrics.states_without_estimate) == (1.0, 1)
