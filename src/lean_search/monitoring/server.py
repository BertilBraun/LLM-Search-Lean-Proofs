"""The dashboard's web server (stdlib only): static pages, a JSON API over the metric files, and authentication.

Every page and API call needs either a session cookie from the login form or HTTP basic auth (any user name, the
dashboard password). The password comes from a file or an environment variable and is never logged.
"""

import base64
import binascii
import dataclasses
import gzip
import hashlib
import hmac
import json
import math
import mimetypes
import secrets
import threading
import time
import tomllib
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lean_search.monitoring.alerts import AlertThresholds, run_alerts
from lean_search.monitoring.store import RunReader, SeriesWindow, downsampled
from lean_search.search.records import from_json_object

STATIC_DIRECTORY = Path(__file__).parent / "static"
SESSION_COOKIE = "lean_dashboard_session"
PASSWORD_VARIABLE = "LEAN_SEARCH_DASHBOARD_PASSWORD"
MAX_POINTS = 2000
DEFAULT_POINTS = 400
LOGIN_BODY_LIMIT = 4096
COMPRESS_ABOVE_BYTES = 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@dataclass(frozen=True)
class DashboardConfig:
    title: str = "Lean RL loop"
    refresh_seconds: float = 30.0
    session_days: float = 14.0
    # Failed logins per client within a minute before further attempts are refused for the rest of it.
    max_failed_logins_per_minute: int = 10
    alerts: AlertThresholds = field(default_factory=AlertThresholds)


def load_config(path: Path | None) -> DashboardConfig:
    if path is None:
        return DashboardConfig()
    return from_json_object(DashboardConfig, tomllib.loads(path.read_text(encoding="utf-8")))


class Authenticator:
    def __init__(self, password: str, session_seconds: float, max_failures_per_minute: int) -> None:
        if not password:
            raise ValueError("the dashboard password is empty")
        self.password_digest = hashlib.sha256(password.encode()).digest()
        # Sessions are signed with a key that lives only in this process: a restart logs everyone out.
        self.session_key = secrets.token_bytes(32)
        self.session_seconds = session_seconds
        self.max_failures = max_failures_per_minute
        self.failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def password_matches(self, password: str) -> bool:
        return hmac.compare_digest(hashlib.sha256(password.encode()).digest(), self.password_digest)

    def locked_out(self, client: str, now: float) -> bool:
        with self.lock:
            recent = self.failures[client]
            while recent and recent[0] < now - 60:
                recent.popleft()
            return len(recent) >= self.max_failures

    def record_failure(self, client: str, now: float) -> None:
        with self.lock:
            self.failures[client].append(now)

    def signature(self, expiry: str) -> str:
        return hmac.new(self.session_key, expiry.encode(), hashlib.sha256).hexdigest()

    def new_session(self, now: float) -> str:
        expiry = str(int(now + self.session_seconds))
        return f"{expiry}.{self.signature(expiry)}"

    def session_valid(self, token: str, now: float) -> bool:
        expiry, _, signature = token.partition(".")
        if not expiry.isdigit() or not hmac.compare_digest(signature, self.signature(expiry)):
            return False
        return int(expiry) > now

    def basic_valid(self, header: str) -> bool:
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(encoded.strip(), validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return False
        _, separator, password = decoded.partition(":")
        return bool(separator) and self.password_matches(password)


@dataclass(frozen=True)
class RunSource:
    name: str
    directory: Path


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        runs: list[RunSource],
        config: DashboardConfig,
        authenticator: Authenticator,
        secure_cookies: bool = False,
    ) -> None:
        super().__init__(address, DashboardHandler)
        assert runs
        self.runs = {run.name: RunReader(run.directory) for run in runs}
        self.main_run = runs[0].name
        self.config = config
        self.authenticator = authenticator
        self.secure_cookies = secure_cookies
        self.static_files = {path.name: path for path in STATIC_DIRECTORY.iterdir() if path.is_file()}


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(f"{value:.6g}")


def json_safe(value: object) -> object:
    match value:
        case float() if not math.isfinite(value):
            return None
        case dict():
            return {key: json_safe(item) for key, item in value.items()}
        case list():
            return [json_safe(item) for item in value]
        case _:
            return value


def window_json(window: SeriesWindow) -> dict[str, Any]:
    return {
        "records": window.records,
        "time": [round(moment, 1) for moment in window.times],
        "phase": window.phases,
        "policy_version": window.policy_versions,
        "value_version": window.value_versions,
        "columns": {name: [rounded(value) for value in values] for name, values in window.columns.items()},
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "LeanDashboard"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Every open page polls several endpoints; an access log would only grow over a multi-day run.
        pass

    def client(self) -> str:
        return self.client_address[0]

    def send_body(
        self, status: HTTPStatus, body: bytes, content_type: str, headers: dict[str, str] | None = None
    ) -> None:
        compress = len(body) > COMPRESS_ABOVE_BYTES and "gzip" in self.headers.get("Accept-Encoding", "")
        if compress:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
        if compress:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        self.send_body(status, body, "application/json; charset=utf-8")

    def redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        self.send_body(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": location, **(headers or {})})

    def session_token(self) -> str | None:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def authenticated(self) -> bool:
        authenticator = self.server.authenticator
        token = self.session_token()
        if token is not None and authenticator.session_valid(token, time.time()):
            return True
        header = self.headers.get("Authorization")
        if header is None:
            return False
        if authenticator.locked_out(self.client(), time.time()):
            return False
        if authenticator.basic_valid(header):
            return True
        authenticator.record_failure(self.client(), time.time())
        return False

    def cookie_header(self, value: str, max_age: int) -> str:
        secure = self.server.secure_cookies or self.headers.get("X-Forwarded-Proto", "").lower() == "https"
        attributes = f"{SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
        return attributes + ("; Secure" if secure else "")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        match path:
            case "/healthz":
                self.send_body(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8")
            case "/login":
                self.send_static("login.html")
            case _ if path.startswith("/static/"):
                self.send_static(path.removeprefix("/static/"))
            case "/favicon.ico":
                self.send_static("favicon.svg")
            case "/" if not self.authenticated():
                self.redirect("login")
            case "/":
                self.send_static("index.html")
            case _ if not path.startswith("/api/"):
                self.send_body(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            case _ if not self.authenticated():
                self.send_json({"error": "authentication required"}, HTTPStatus.UNAUTHORIZED)
            case "/api/runs":
                self.send_json(self.runs_response())
            case "/api/overview":
                self.api_call(lambda: self.overview_response(query))
            case "/api/series":
                self.api_call(lambda: self.series_response(query))
            case _:
                self.send_json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        match urlsplit(self.path).path.rstrip("/"):
            case "/login":
                self.login()
            case "/logout":
                self.redirect("login", {"Set-Cookie": self.cookie_header("", 0)})
            case _:
                self.send_body(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def login(self) -> None:
        authenticator = self.server.authenticator
        now = time.time()
        if authenticator.locked_out(self.client(), now):
            self.redirect("login?error=locked")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > LOGIN_BODY_LIMIT:
            self.send_body(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"too large\n", "text/plain; charset=utf-8")
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        password = form.get("password", [""])[-1]
        if not authenticator.password_matches(password):
            authenticator.record_failure(self.client(), now)
            self.redirect("login?error=invalid")
            return
        max_age = int(authenticator.session_seconds)
        self.redirect("./", {"Set-Cookie": self.cookie_header(authenticator.new_session(now), max_age)})

    def send_static(self, name: str) -> None:
        path = self.server.static_files.get(name)
        if path is None:
            self.send_body(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith(("javascript", "svg+xml")):
            content_type += "; charset=utf-8"
        self.send_body(HTTPStatus.OK, path.read_bytes(), content_type)

    def api_call(self, respond: Callable[[], dict[str, Any]]) -> None:
        try:
            self.send_json(respond())
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def reader(self, query: dict[str, str]) -> RunReader:
        name = query.get("run", self.server.main_run)
        if name not in self.server.runs:
            raise ValueError(f"unknown run {name!r}")
        return self.server.runs[name]

    def runs_response(self) -> dict[str, Any]:
        return {
            "main": self.server.main_run,
            "runs": {name: reader.families() for name, reader in self.server.runs.items()},
        }

    def overview_response(self, query: dict[str, str]) -> dict[str, Any]:
        reader = self.reader(query)
        now = time.time()
        latest = {}
        for family in reader.families():
            series = reader.series(family)
            if series.latest is not None:
                latest[family] = series.latest
        config = self.server.config
        return {
            "title": config.title,
            "run": query.get("run", self.server.main_run),
            "now": now,
            "refresh_seconds": config.refresh_seconds,
            "thresholds": dataclasses.asdict(config.alerts),
            "alerts": [dataclasses.asdict(alert) for alert in run_alerts(reader, config.alerts, now)],
            "latest": json_safe(latest),
        }

    def series_response(self, query: dict[str, str]) -> dict[str, Any]:
        reader = self.reader(query)
        family = query.get("family", "")
        if family not in reader.families():
            raise ValueError(f"unknown family {family!r}")
        points = min(MAX_POINTS, max(1, int(query.get("points", DEFAULT_POINTS))))
        since = float(query["since"]) if "since" in query else None
        fields = set(query["fields"].split(",")) if query.get("fields") else None
        window = downsampled(reader.series(family), points, since, fields)
        return {"family": family, **window_json(window)}
