"""A stand-in for the vLLM server endpoints that `policy.server_control` and the policy client call (health, sleep,
wake, weight reload, models, completions), on a local port: it records which weights each reload loaded, answers a
completion with its prompt, and can fail: a 500 for the next requests or for given prompts, or die (stop listening,
the request in flight unanswered) after a number of completions; `revive` starts it again on its port."""

import json
import threading
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
    # Prompts always answered with a 500.
    failing_prompts: set[str] = field(default_factory=set)
    # After this many more completions the server dies; 0: never.
    completions_until_death: int = 0
    completions: int = 0
    # Dead: no request is answered, on kept-alive connections either.
    dead: bool = False


def completion(prompt: str) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "text": f"answer to {prompt}",
                "logprobs": {"tokens": ["token_id:1"], "token_logprobs": [-0.5]},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class FakeVllmServer:
    def __init__(self) -> None:
        self.state = FakeServerState()
        self.deaths = 0
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
                        self.complete(body["prompt"])
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

            def complete(self, prompt: str) -> None:
                state.completions += 1
                if state.completions_until_death and state.completions >= state.completions_until_death:
                    # A segfaulting engine: the request in flight is never answered and the port closes.
                    state.completions_until_death = 0
                    state.dead = True
                    self.close_connection = True
                    threading.Thread(target=fake.die).start()
                    return
                if state.failures_left or prompt in state.failing_prompts:
                    state.failures_left = max(0, state.failures_left - 1)
                    self.reply({"error": "EngineCore encountered an issue"}, 500)
                    return
                self.reply(completion(prompt))

        self.handler = Handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.serve()

    def serve(self) -> None:
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
        self.state.dead = False
        self.state.completions = 0
        self.state.completions_until_death = completions_until_death
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), self.handler)
        self.serve()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
