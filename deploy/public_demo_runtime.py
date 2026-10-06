"""Run the private synthetic API and the public Next server as one container."""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

API_PORT = 8011
API_URL = f"http://127.0.0.1:{API_PORT}"
DEFAULT_PORT = 10000


def public_port(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("PORT must be a decimal integer.")
    port = int(value)
    if not 1 <= port <= 65535 or port == API_PORT:
        raise ValueError("PORT must be between 1 and 65535 and must not be 8011.")
    return port


def child_environment(service: str, port: int) -> dict[str, str]:
    # Never copy os.environ: provider secrets, proxy settings, Python/Node
    # preload options and application configuration must not reach either child.
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }
    if service == "API":
        environment.update(
            PYTHONUNBUFFERED="1",
            PYTHONDONTWRITEBYTECODE="1",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
        )
    elif service == "frontend":
        environment.update(
            NODE_ENV="production",
            NODE_OPTIONS="--max-old-space-size=192",
            NEXT_TELEMETRY_DISABLED="1",
            HOSTNAME="0.0.0.0",
            PORT=str(port),
            RESEARCH_API_URL=API_URL,
        )
    else:
        raise ValueError(f"Unknown demo service: {service}")
    return environment


def healthy(base_url: str, timeout: float = 2.0) -> bool:
    # Loopback probes must never use an inherited HTTP proxy. Bound the body too.
    try:
        with build_opener(ProxyHandler({})).open(
            f"{base_url}/api/health", timeout=timeout
        ) as response:
            body = json.loads(response.read(4097))
            return (
                response.status == 200
                and isinstance(body, dict)
                and body.get("status") == "ok"
                and body.get("database") == "connected"
                and isinstance(body.get("version"), str)
            )
    except (OSError, URLError, HTTPException, ValueError):
        return False


def log(message: str) -> None:
    print(f"Public demo: {message}", file=sys.stderr, flush=True)


def _exit_code(code: int) -> int:
    # Even a clean child exit is an unexpected loss of this two-process service.
    return code if code > 0 else 128 - code if code < 0 else 1


def _stop(children: list[subprocess.Popen], timeout: float) -> None:
    def send(child, sig):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass

    for child in children:
        send(child, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while any(child.poll() is None for child in children) and time.monotonic() < deadline:
        time.sleep(0.025)
    # Kill remaining process groups, including descendants of an exited leader.
    for child in children:
        send(child, signal.SIGKILL)
    deadline = time.monotonic() + 1.0
    for child in children:
        try:
            child.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            log(f"Could not reap child {child.pid} after SIGKILL.")


def supervise(
    api_command: Sequence[str],
    frontend_command: Sequence[str],
    *,
    port: int,
    api_url: str = API_URL,
    frontend_cwd: str | None = None,
    startup_timeout: float = 300.0,
    shutdown_timeout: float = 5.0,
) -> int:
    """Own exactly two child processes; injectable commands support lifecycle tests.

    The deployment CLI exposes none of these command/URL/timeout overrides.
    API package verification occurs inside public_demo.py before it binds a socket.
    """
    public_port(str(port))
    children: list[subprocess.Popen] = []
    stopped = threading.Event()
    received_signal = 0

    def request_stop(signum, _frame):
        nonlocal received_signal
        if not received_signal:
            received_signal = signum
        stopped.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}

    def start(service, command, cwd=None):
        child = subprocess.Popen(
            command,
            cwd=cwd,
            env=child_environment(service, port),
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        children.append(child)
        log(f"{service} started (pid {child.pid}).")
        return child

    try:
        if stopped.is_set():
            return 128 + received_signal
        api = start("API", api_command)
        deadline = time.monotonic() + startup_timeout
        while not stopped.is_set():
            if (code := api.poll()) is not None:
                log(f"API exited before readiness (status {code}).")
                return _exit_code(code)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log("API readiness timed out.")
                return 1
            if healthy(api_url, timeout=min(0.5, remaining)):
                # The child can fail while a probe is in flight.
                if (code := api.poll()) is not None:
                    log(f"API exited before readiness (status {code}).")
                    return _exit_code(code)
                break
            stopped.wait(min(0.05, remaining))
        if stopped.is_set():
            return 128 + received_signal
        start("frontend", frontend_command, frontend_cwd)
        while not stopped.is_set():
            for service, child in zip(("API", "frontend"), children, strict=True):
                if (code := child.poll()) is not None:
                    log(f"{service} exited (status {code}); stopping the demo.")
                    return _exit_code(code)
            stopped.wait(0.05)
        return 128 + received_signal
    except OSError as exc:
        log(f"Unable to start the demo: {exc}")
        return 1
    finally:
        _stop(children, shutdown_timeout)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "health"), nargs="?", default="run")
    args = parser.parse_args(argv)
    try:
        port = public_port(os.environ.get("PORT", str(DEFAULT_PORT)))
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "health":
        return 0 if healthy(f"http://127.0.0.1:{port}") else 1
    return supervise(
        (
            sys.executable,
            "/app/examples/public_demo.py",
            "serve",
            "--directory",
            "/app/demo",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
        ),
        ("/usr/local/bin/node", "/app/web/server.js"),
        port=port,
        frontend_cwd="/app/web",
    )


if __name__ == "__main__":
    sys.exit(main())
