import base64
import gzip
import http.client
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import pytest
from metric_records import grpo_phase, loop_status

from lean_search.monitoring.families import FixedTargets
from lean_search.monitoring.server import (
    SESSION_COOKIE,
    Authenticator,
    DashboardConfig,
    DashboardServer,
    RunSource,
    load_config,
)
from lean_search.monitoring.store import MetricsWriter

PASSWORD = "test-password-for-the-suite"
MAX_FAILURES = 3
SHIPPED_CONFIG = Path(__file__).parents[2] / "experiments/configs/dashboard/dashboard.toml"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        return json.loads(self.body)


@dataclass(frozen=True)
class Dashboard:
    port: int

    def request(
        self, method: str, path: str, headers: dict[str, str] | None = None, body: str | None = None
    ) -> Response:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = Response(
            response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
        )
        connection.close()
        return result

    def get(self, path: str, headers: dict[str, str] | None = None) -> Response:
        return self.request("GET", path, headers)

    def login(self, password: str) -> Response:
        form = urlencode({"password": password})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self.request("POST", "/login", headers, form)


def basic(password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"owner:{password}".encode()).decode()}


def write_run(directory: Path) -> None:
    writer = MetricsWriter(directory)
    for index in range(20):
        writer.write(grpo_phase(kl=0.01 * index), record_time=1000.0 + index)
    writer.write(FixedTargets(minif2f_valid_solved=171, minif2f_valid_problems=244), record_time=1000.0)
    writer.write(loop_status(last_publish_time=time.time()), record_time=time.time())


def running_dashboard(directory: Path, authenticator: Authenticator | None) -> Iterator[Dashboard]:
    write_run(directory / "main")
    write_run(directory / "control")
    runs = [RunSource("main", directory / "main"), RunSource("control", directory / "control")]
    config = DashboardConfig(max_failed_logins_per_minute=MAX_FAILURES)
    server = DashboardServer(("127.0.0.1", 0), runs, config, authenticator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Dashboard(server.server_address[1])
    server.shutdown()
    server.server_close()


@pytest.fixture
def dashboard(tmp_path: Path) -> Iterator[Dashboard]:
    yield from running_dashboard(tmp_path, Authenticator(PASSWORD, 3600, MAX_FAILURES))


@pytest.fixture
def open_dashboard(tmp_path: Path) -> Iterator[Dashboard]:
    yield from running_dashboard(tmp_path, None)


@pytest.mark.parametrize("path", ["/api/runs", "/api/overview", "/api/series?family=grpo"])
def test_open_dashboard_needs_no_authentication(open_dashboard: Dashboard, path: str) -> None:
    assert open_dashboard.get(path).status == 200


def test_open_dashboard_serves_the_page_without_login(open_dashboard: Dashboard) -> None:
    assert open_dashboard.get("/").status == 200


def test_open_dashboard_sends_the_login_page_home(open_dashboard: Dashboard) -> None:
    assert open_dashboard.get("/login").headers["location"] == "./"


@pytest.mark.parametrize(("fixture", "expected"), [("open_dashboard", False), ("dashboard", True)])
def test_overview_reports_whether_authentication_is_on(
    request: pytest.FixtureRequest, fixture: str, expected: bool
) -> None:
    served: Dashboard = request.getfixturevalue(fixture)
    assert served.get("/api/overview", basic(PASSWORD)).json()["authentication"] is expected


def session_cookie(response: Response) -> str:
    return response.headers["set-cookie"].split(";")[0]


@pytest.mark.parametrize("path", ["/api/runs", "/api/overview", "/api/series?family=grpo"])
def test_api_requires_authentication(dashboard: Dashboard, path: str) -> None:
    assert dashboard.get(path).status == 401


def test_page_redirects_to_login_without_authentication(dashboard: Dashboard) -> None:
    assert dashboard.get("/").headers["location"] == "login"


def test_basic_auth_is_accepted(dashboard: Dashboard) -> None:
    assert dashboard.get("/api/runs", basic(PASSWORD)).status == 200


def test_basic_auth_with_wrong_password_is_refused(dashboard: Dashboard) -> None:
    assert dashboard.get("/api/runs", basic("wrong")).status == 401


def test_wrong_login_redirects_back_with_an_error(dashboard: Dashboard) -> None:
    assert dashboard.login("wrong").headers["location"] == "login?error=invalid"


def test_wrong_login_sets_no_cookie(dashboard: Dashboard) -> None:
    assert "set-cookie" not in dashboard.login("wrong").headers


def test_login_cookie_opens_the_api(dashboard: Dashboard) -> None:
    cookie = session_cookie(dashboard.login(PASSWORD))
    assert dashboard.get("/api/runs", {"Cookie": cookie}).status == 200


@pytest.mark.parametrize("attribute", ["HttpOnly", "SameSite=Strict", "Path=/"])
def test_session_cookie_is_restricted(dashboard: Dashboard, attribute: str) -> None:
    assert attribute in dashboard.login(PASSWORD).headers["set-cookie"]


def test_session_cookie_is_secure_behind_https(dashboard: Dashboard) -> None:
    form = urlencode({"password": PASSWORD})
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-Proto": "https"}
    assert "Secure" in dashboard.request("POST", "/login", headers, form).headers["set-cookie"]


def test_tampered_cookie_is_refused(dashboard: Dashboard) -> None:
    expiry = int(time.time()) + 3600
    assert dashboard.get("/api/runs", {"Cookie": f"{SESSION_COOKIE}={expiry}.{'0' * 64}"}).status == 401


def test_repeated_failures_lock_out_even_the_right_password(dashboard: Dashboard) -> None:
    for _ in range(MAX_FAILURES):
        dashboard.login("wrong")
    assert dashboard.login(PASSWORD).headers["location"] == "login?error=locked"


def test_expired_session_is_refused() -> None:
    authenticator = Authenticator(PASSWORD, session_seconds=10, max_failures_per_minute=MAX_FAILURES)
    token = authenticator.new_session(now=1000.0)
    assert not authenticator.session_valid(token, now=1011.0)


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        Authenticator("", 10, MAX_FAILURES)


@pytest.mark.parametrize("path", ["/login", "/healthz", "/static/style.css"])
def test_public_paths_need_no_authentication(dashboard: Dashboard, path: str) -> None:
    assert dashboard.get(path).status == 200


@pytest.mark.parametrize("path", ["/static/../server.py", "/static/missing.js", "/elsewhere"])
def test_unknown_files_are_not_served(dashboard: Dashboard, path: str) -> None:
    assert dashboard.get(path, basic(PASSWORD)).status == 404


@pytest.mark.parametrize("header", ["content-security-policy", "x-content-type-options", "referrer-policy"])
def test_responses_carry_security_headers(dashboard: Dashboard, header: str) -> None:
    assert header in dashboard.get("/login").headers


def test_runs_lists_families_per_run(dashboard: Dashboard) -> None:
    assert dashboard.get("/api/runs", basic(PASSWORD)).json()["runs"]["control"] == ["fixed_targets", "grpo", "status"]


def test_series_is_downsampled_to_the_requested_points(dashboard: Dashboard) -> None:
    response = dashboard.get("/api/series?family=grpo&points=5", basic(PASSWORD)).json()
    assert len(response["columns"]["kl_to_behaviour_policy"]) == 5


def test_series_reports_the_records_in_the_window(dashboard: Dashboard) -> None:
    assert dashboard.get("/api/series?family=grpo&since=1010", basic(PASSWORD)).json()["records"] == 10


def test_series_of_another_run(dashboard: Dashboard) -> None:
    response = dashboard.get("/api/series?family=fixed_targets&run=control", basic(PASSWORD)).json()
    assert response["columns"]["minif2f_valid_solved"] == [171.0]


@pytest.mark.parametrize("query", ["family=missing", "family=grpo&run=missing", "family=grpo&points=many"])
def test_bad_series_requests_are_rejected(dashboard: Dashboard, query: str) -> None:
    assert dashboard.get(f"/api/series?{query}", basic(PASSWORD)).status == 400


def test_overview_raises_alerts(dashboard: Dashboard) -> None:
    titles = {alert["title"] for alert in dashboard.get("/api/overview", basic(PASSWORD)).json()["alerts"]}
    assert "KL high" in titles


def test_overview_has_the_latest_record_per_family(dashboard: Dashboard) -> None:
    latest = dashboard.get("/api/overview", basic(PASSWORD)).json()["latest"]
    assert latest["grpo"]["fields"]["kl_to_behaviour_policy"] == pytest.approx(0.19)


def test_large_responses_are_compressed(dashboard: Dashboard) -> None:
    headers = {**basic(PASSWORD), "Accept-Encoding": "gzip"}
    response = dashboard.get("/api/series?family=grpo", headers)
    assert json.loads(gzip.decompress(response.body))["family"] == "grpo"


def test_shipped_config_matches_the_defaults() -> None:
    assert load_config(SHIPPED_CONFIG) == DashboardConfig()


def test_config_file_overrides_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text('title = "Control"\n[alerts]\nmax_kl = 0.1\n', encoding="utf-8")
    assert load_config(path).alerts.max_kl == 0.1
