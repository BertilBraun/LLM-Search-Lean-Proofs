"""A stand-in for the vLLM server endpoints that `policy.server_control` and the policy client call (health, sleep,
wake, weight reload, models, completions), on a local port: it records which weights each reload loaded, answers a
completion with its prompt (the top next tokens' log-probabilities shifted by `logprob_shift`: other weights), and
can fail: a 500 for the next requests or for given prompts, a 400 for given prompts, a 503 for the next /health
checks, 500s while asleep, or die (stop listening, the request in flight unanswered) after a number of completions.
`revive` starts it again on its port as a fresh server would (awake, without pending failures)."""

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


@dataclass
class FakeServerState:
    sleeping: bool = False
    reloads: list[str] = field(default_factory=list)
    # /v1/models' root: the directory the server started from.
    root: str = "/started/from"
    # The next completions answered with a 500.
    failures_left: int = 0
    # Prompts always answered with a 500, and with a 400 (a request the server refuses).
    failing_prompts: set[str] = field(default_factory=set)
    refused_prompts: set[str] = field(default_factory=set)
    # The next /health checks answered with a 503.
    health_failures_left: int = 0
    # After this many more completions the server dies; 0: never.
    completions_until_death: int = 0
    completions: int = 0
    # Dead: no request is answered, on kept-alive connections either.
    dead: bool = False
    # Added to every top log-probability: a server holding other weights.
    logprob_shift: float = 0.0
    # The next completions answered only after this delay (a stall).
    slow_completions_left: int = 0
    completion_delay_seconds: float = 0.0


def choice(index: int, prompt: str, shift: float) -> dict:
    top = {"token_id:1": -0.1 + shift, "token_id:2": -2.5 + shift, "token_id:3": -3.0, "token_id:4": -4.0}
    return {
        "index": index,
        "text": f"answer to {prompt}",
        "logprobs": {"tokens": ["token_id:1"], "token_logprobs": [-0.5], "top_logprobs": [top]},
        "finish_reason": "stop",
    }


def completion(prompts: list[str], shift: float) -> dict:
    return {
        "choices": [choice(index, prompt, shift) for index, prompt in enumerate(prompts)],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        # A client that timed out a stalled answer closed its connection.
        return


class FakeVllmServer:
    def __init__(self) -> None:
        self.state = FakeServerState()
        self.deaths = 0
        self.listening = False
        state = self.state
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *arguments: object) -> None:
                return

            def reply(self, body: dict, status: int = 200) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def answers(self) -> bool:
                if state.dead:
                    self.close_connection = True
                return not state.dead

            def do_GET(self) -> None:
                if not self.answers():
                    return
                match urlparse(self.path).path:
                    case "/health" if state.health_failures_left:
                        state.health_failures_left -= 1
                        self.reply({}, 503)
                    case "/health":
                        self.reply({})
                    case "/is_sleeping":
                        self.reply({"is_sleeping": state.sleeping})
                    case "/v1/models":
                        self.reply({"data": [{"id": "fake", "root": state.root}]})

            def do_POST(self) -> None:
                if not self.answers():
                    return
                request = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else {}
                match request.path:
                    case "/v1/completions":
                        prompt = body["prompt"]
                        self.complete(prompt if isinstance(prompt, list) else [prompt])
                        return
                    case "/sleep":
                        state.sleeping = True
                    case "/wake_up" if parse_qs(request.query).get("tags") == ["kv_cache"]:
                        state.sleeping = False
                    case "/collective_rpc":
                        state.reloads.append(body["kwargs"]["weights_path"])
                    case "/reset_prefix_cache":
                        self.reply({"success": True})
                        return
                self.reply({})

            def complete(self, prompts: list[str]) -> None:
                state.completions += 1
                if state.slow_completions_left:
                    state.slow_completions_left -= 1
                    time.sleep(state.completion_delay_seconds)
                if state.completions_until_death and state.completions >= state.completions_until_death:
                    # A segfaulting engine: the request in flight is never answered and the port closes.
                    state.completions_until_death = 0
                    state.dead = True
                    self.close_connection = True
                    threading.Thread(target=fake.die).start()
                    return
                if set(prompts) & state.refused_prompts:
                    self.reply({"error": "This model's maximum context length is 8192 tokens"}, 400)
                    return
                if state.failures_left or state.sleeping or set(prompts) & state.failing_prompts:
                    state.failures_left = max(0, state.failures_left - 1)
                    self.reply({"error": "EngineCore encountered an issue"}, 500)
                    return
                self.reply(completion(prompts, state.logprob_shift))

        self.handler = Handler
        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.serve()

    def serve(self) -> None:
        self.listening = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def die(self) -> None:
        self.state.dead = True
        self.deaths += 1
        self.close()

    def revive(self, completions_until_death: int = 0) -> None:
        if self.listening:
            self.close()
        self.state.dead = False
        self.state.sleeping = False
        self.state.failures_left = 0
        self.state.health_failures_left = 0
        self.state.completions = 0
        self.state.completions_until_death = completions_until_death
        self.server = QuietServer(("127.0.0.1", self.port), self.handler)
        self.serve()

    def close(self) -> None:
        if self.listening:
            self.listening = False
            self.server.shutdown()
            self.server.server_close()
