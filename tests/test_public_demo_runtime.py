"""Exercise the container supervisor with real children and loopback HTTP."""

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/public_demo_runtime.py"
CANARY = "synthetic-runtime-environment-canary"
SPEC = importlib.util.spec_from_file_location("public_demo_runtime", SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)

CHILD = r"""
import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

role, directory, port, mode = sys.argv[1:]
root = Path(directory)

def stop(signum, frame):
    (root / (role + ".terminated")).write_text(str(signum))
    if mode != "ignore-term":
        raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
(root / (role + ".json")).write_text(json.dumps({
    "pid": os.getpid(), "env": dict(os.environ), "started": time.monotonic_ns()
}))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/health":
            self.send_error(404)
            return
        body = (
            b'{"status":"ok"}' if mode == "wrong-health" else
            b'{"status":"ok","database":"connected","version":"test"}'
        )
        (root / "api.probed").write_text(str(time.monotonic_ns()))
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

server = None
if role == "api" and mode != "unready":
    server = HTTPServer(("127.0.0.1", int(port)), Handler)
    server.timeout = 0.02
while True:
    exit_file = root / (role + ".exit")
    if exit_file.exists():
        raise SystemExit(int(exit_file.read_text()))
    if server:
        server.handle_request()
    else:
        time.sleep(0.02)
"""


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def await_file(path, process, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except ValueError:
                pass  # A child may still be writing its short record.
        assert process.poll() is None, process.returncode
        time.sleep(0.02)
    pytest.fail(f"Timed out waiting for {path.name}")


def assert_reaped(record):
    with pytest.raises(ProcessLookupError):
        os.kill(record["pid"], 0)


@pytest.fixture
def launch(tmp_path):
    child_script = tmp_path / "child.py"
    child_script.write_text(CHILD)
    processes = []
    logs = []

    def start(
        *,
        api_mode="ready",
        web_mode="ready",
        api_command=None,
        web_command=None,
        startup_timeout=2,
    ):
        api_port = free_port()
        port = free_port()
        api_command = api_command or [
            sys.executable,
            str(child_script),
            "api",
            str(tmp_path),
            str(api_port),
            api_mode,
        ]
        web_command = web_command or [
            sys.executable,
            str(child_script),
            "frontend",
            str(tmp_path),
            str(port),
            web_mode,
        ]
        driver = (
            f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); "
            "from public_demo_runtime import supervise; "
            f"sys.exit(supervise({api_command!r}, {web_command!r}, port={port}, "
            f"api_url='http://127.0.0.1:{api_port}', startup_timeout={startup_timeout}, "
            "shutdown_timeout=0.2))"
        )
        log = (tmp_path / "supervisor.log").open("w")
        logs.append(log)
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", driver],
            stdout=log,
            stderr=log,
            env={
                "PORT": str(port),
                "OPENAI_API_KEY": CANARY,
                "RESEARCHDESK_PROVIDER": CANARY,
                "RESEARCHDESK_OPERATOR_TOKEN": CANARY,
                "RESEARCHDESK_DATABASE_URL": CANARY,
                "RESEARCH_API_URL": CANARY,
                "NODE_OPTIONS": CANARY,
                "PYTHONPATH": CANARY,
                "HTTPS_PROXY": CANARY,
                "HTTP_PROXY": CANARY,
                "HOME": CANARY,
            },
        )
        processes.append(process)
        return process, port

    yield start
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        # A failed assertion must not leave either isolated child session behind.
        for record in tmp_path.glob("*.json"):
            try:
                pid = json.loads(record.read_text())["pid"]
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, KeyError, ValueError):
                pass
    for log in logs:
        log.close()


@pytest.mark.parametrize("value", ["0", "8011", "65536", "-1", "1.5", " 10000", "x", ""])
def test_invalid_public_port_fails_before_starting_children(value):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], env={"PORT": value}, capture_output=True, timeout=3
    )
    assert result.returncode == 2
    assert b"PORT must" in result.stderr
    assert b"started (pid" not in result.stderr


def test_port_defaults_and_fixed_commands(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    calls = []
    monkeypatch.setattr(runtime, "supervise", lambda *args, **kwargs: calls.append((args, kwargs)))
    runtime.main([])
    args, options = calls[0]
    assert args[0] == (
        sys.executable,
        "/app/examples/public_demo.py",
        "serve",
        "--directory",
        "/app/demo",
        "--host",
        "127.0.0.1",
        "--port",
        "8011",
    )
    assert args[1] == ("/usr/local/bin/node", "/app/web/server.js")
    assert options == {"port": 10000, "frontend_cwd": "/app/web"}


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_startup_environment_isolation_and_signal_cleanup(launch, tmp_path, signum):
    process, port = launch()
    api = await_file(tmp_path / "api.json", process)
    frontend = await_file(tmp_path / "frontend.json", process)
    assert int((tmp_path / "api.probed").read_text()) < frontend["started"]
    for service, record in (("API", api), ("frontend", frontend)):
        # The Python/OS runtime may add its own locale fields after process start.
        platform_fields = {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}
        observed = {
            key: value for key, value in record["env"].items() if key not in platform_fields
        }
        assert observed == runtime.child_environment(service, port)
        assert CANARY not in json.dumps(record)
    assert frontend["env"]["RESEARCH_API_URL"] == "http://127.0.0.1:8011"
    assert frontend["env"]["HOSTNAME"] == "0.0.0.0"
    process.send_signal(signum)
    assert process.wait(timeout=3) == 128 + signum
    for role, record in (("api", api), ("frontend", frontend)):
        assert (tmp_path / f"{role}.terminated").read_text() == str(signal.SIGTERM)
        assert_reaped(record)


def test_startup_timeout_never_starts_frontend(launch, tmp_path):
    process, _ = launch(api_mode="unready", startup_timeout=0.4)
    api = await_file(tmp_path / "api.json", process)
    assert process.wait(timeout=3) == 1
    assert not (tmp_path / "frontend.json").exists()
    assert "API readiness timed out" in (tmp_path / "supervisor.log").read_text()
    assert_reaped(api)


@pytest.mark.parametrize("code", [0, 7])
def test_api_failure_before_readiness_is_nonzero(launch, tmp_path, code):
    (tmp_path / "api.exit").write_text(str(code))
    process, _ = launch(api_mode="unready")
    assert process.wait(timeout=3) == (code or 1)
    assert not (tmp_path / "frontend.json").exists()
    assert_reaped(json.loads((tmp_path / "api.json").read_text()))


@pytest.mark.parametrize("role", ["api", "frontend"])
@pytest.mark.parametrize("code", [0, 7])
def test_child_exit_stops_sibling_even_after_clean_exit(launch, tmp_path, role, code):
    process, _ = launch()
    api = await_file(tmp_path / "api.json", process)
    frontend = await_file(tmp_path / "frontend.json", process)
    (tmp_path / f"{role}.exit").write_text(str(code))
    assert process.wait(timeout=3) == (code or 1)
    sibling = "frontend" if role == "api" else "api"
    assert (tmp_path / f"{sibling}.terminated").exists()
    assert_reaped(api)
    assert_reaped(frontend)


def test_signal_during_api_startup_cleans_up(launch, tmp_path):
    process, _ = launch(api_mode="unready")
    api = await_file(tmp_path / "api.json", process)
    process.terminate()
    assert process.wait(timeout=3) == 128 + signal.SIGTERM
    assert not (tmp_path / "frontend.json").exists()
    assert_reaped(api)


def test_shutdown_kills_and_reaps_children_that_ignore_term(launch, tmp_path):
    process, _ = launch(api_mode="ignore-term", web_mode="ignore-term")
    api = await_file(tmp_path / "api.json", process)
    frontend = await_file(tmp_path / "frontend.json", process)
    process.terminate()
    assert process.wait(timeout=3) == 128 + signal.SIGTERM
    assert_reaped(api)
    assert_reaped(frontend)


def test_spawn_failure_returns_nonzero(launch, tmp_path):
    process, _ = launch(api_command=[str(tmp_path / "nonexistent")])
    assert process.wait(timeout=3) == 1
    assert not (tmp_path / "frontend.json").exists()


def test_frontend_spawn_failure_cleans_up_api(launch, tmp_path):
    process, _ = launch(web_command=[str(tmp_path / "nonexistent")])
    assert process.wait(timeout=3) == 1
    assert_reaped(json.loads((tmp_path / "api.json").read_text()))


def test_killed_child_stops_sibling(launch, tmp_path):
    process, _ = launch()
    api = await_file(tmp_path / "api.json", process)
    frontend = await_file(tmp_path / "frontend.json", process)
    os.kill(api["pid"], signal.SIGKILL)
    assert process.wait(timeout=3) == 128 + signal.SIGKILL
    assert_reaped(api)
    assert_reaped(frontend)


def test_malformed_package_fails_before_frontend_starts(launch, tmp_path):
    package = tmp_path / "bad-demo"
    package.mkdir()
    (package / "manifest.json").write_text("{}")
    (package / "researchdesk.db").write_bytes(b"not a database")
    process, _ = launch(
        api_command=[
            sys.executable,
            str(ROOT / "examples/public_demo.py"),
            "serve",
            "--directory",
            str(package),
            "--host",
            "127.0.0.1",
            "--port",
            str(free_port()),
        ],
        startup_timeout=10,
    )
    assert process.wait(timeout=12) == 2
    assert not (tmp_path / "frontend.json").exists()
    assert "Malformed demo package" in (tmp_path / "supervisor.log").read_text()


def test_health_returns_failure_when_public_listener_is_absent():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "health"],
        env={"PORT": str(free_port())},
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 1
    assert b"started (pid" not in result.stderr


@pytest.mark.parametrize("mode,expected", [("ready", 0), ("wrong-health", 1)])
def test_health_probes_public_port_without_starting_services(tmp_path, mode, expected):
    port = free_port()
    child_script = tmp_path / "child.py"
    child_script.write_text(CHILD)
    responder = subprocess.Popen(
        [sys.executable, str(child_script), "api", str(tmp_path), str(port), mode],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await_file(tmp_path / "api.json", responder)
        # Wait for the listener rather than relying on process scheduling.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.02)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "health"],
            env={"PORT": str(port), "HTTP_PROXY": "http://127.0.0.1:1"},
            capture_output=True,
            timeout=3,
        )
        assert result.returncode == expected
        assert b"started (pid" not in result.stderr
        assert (tmp_path / "api.probed").exists()
    finally:
        responder.terminate()
        responder.wait(timeout=3)
