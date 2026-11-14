"""A stand-in for the vLLM server control endpoints that `policy.server_control` calls (health, sleep, wake, weight
reload), on a local port: it records which weights each reload loaded."""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


@dataclass
class FakeServerState:
    sleeping: bool = False
    reloads: list[str] = field(default_factory=list)


class FakeVllmServer:
    def __init__(self) -> None:
        self.state = FakeServerState()
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *arguments: object) -> None:
                return

            def reply(self, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                match urlparse(self.path).path:
                    case "/health":
                        self.reply({})
                    case "/is_sleeping":
                        self.reply({"is_sleeping": state.sleeping})

            def do_POST(self) -> None:
                request = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else {}
                match request.path:
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

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
