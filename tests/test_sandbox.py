import os
import shutil
import subprocess
import threading
import time
import uuid

import pytest

from researchdesk.sandbox import DockerSandbox


def test_missing_container_runtime_never_falls_back_to_host(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    result = DockerSandbox(docker_binary="definitely-not-a-docker-binary").run(
        f"def run(payload):\n open({str(sentinel)!r}, 'w').write('unsafe')\n return 1", {}
    )
    assert not result.ok and result.error["code"] == "sandbox_unavailable"
    assert not sentinel.exists()


@pytest.fixture
def sandbox():
    value = DockerSandbox(image=os.environ.get("RESEARCHDESK_SANDBOX_IMAGE", "python:3.12-slim"))
    if not value.availability()["available"]:
        pytest.skip("Docker daemon and configured image required")
    return value


@pytest.mark.sandbox
def test_generated_code_receives_only_supplied_prefix_and_no_host_secrets(sandbox, monkeypatch):
    monkeypatch.setenv("RESEARCHDESK_TEST_SECRET", "not-in-container")
    source = """import os, socket
def run(payload):
    result = {'payload': payload, 'secret': os.environ.get('RESEARCHDESK_TEST_SECRET')}
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=0.5)
        result['network'] = True
    except OSError:
        result['network'] = False
    try:
        open('/forbidden', 'w').write('bad')
        result['root_write'] = True
    except OSError:
        result['root_write'] = False
    return result
"""
    payload = {"history": [{"session": "2026-01-02", "close": 100}]}
    result = sandbox.run(source, payload)
    assert result.ok, result.error
    assert result.output == {
        "payload": payload,
        "secret": None,
        "network": False,
        "root_write": False,
    }


@pytest.mark.sandbox
def test_generated_code_timeout_and_output_bound(sandbox):
    result = sandbox.run("def run(payload):\n while True: pass", {}, timeout_seconds=2)
    assert not result.ok and result.error["code"] == "sandbox_timeout"
    result = sandbox.run("def run(payload):\n print('a' * 400000)\n return 1", {})
    assert not result.ok and result.error["code"] == "sandbox_output_limit"
    assert len(result.stdout.encode()) <= sandbox.output_limit_bytes


@pytest.mark.sandbox
def test_cancellation_terminates_container(sandbox):
    cancelled = threading.Event()
    timer = threading.Timer(1.5, cancelled.set)
    timer.start()
    started = time.monotonic()
    try:
        result = sandbox.run("def run(payload):\n while True: pass", {}, cancelled=cancelled.is_set)
    finally:
        timer.cancel()
    assert not result.ok and result.error["code"] == "cancelled"
    assert time.monotonic() - started < 10


@pytest.mark.sandbox
def test_crash_recovery_cleanup_removes_only_expired_owned_containers(sandbox):
    binary = shutil.which(sandbox.docker_binary)
    suffix = uuid.uuid4().hex
    names = [
        "researchdesk-expired-" + suffix,
        "researchdesk-active-" + suffix,
        "unrelated-fixture-" + suffix,
    ]
    deadlines = ["0", str(time.time() + 600), "0"]
    created = []
    try:
        for name, deadline in zip(names, deadlines, strict=True):
            result = subprocess.run(
                [
                    binary,
                    "create",
                    "--name",
                    name,
                    "--label=researchdesk.sandbox=true",
                    f"--label=researchdesk.expires_at={deadline}",
                    sandbox.image,
                    "python",
                    "-c",
                    "pass",
                ],
                capture_output=True,
                check=True,
                timeout=10,
            )
            created.append(result.stdout.decode().strip())
        assert sandbox.cleanup_expired()["removed"] >= 1
        checks = [
            subprocess.run(
                [binary, "inspect", identifier], capture_output=True, check=False, timeout=5
            ).returncode
            for identifier in created
        ]
        assert checks[0] != 0
        assert checks[1:] == [0, 0]
    finally:
        if created:
            subprocess.run(
                [binary, "rm", "--force", *created], capture_output=True, check=False, timeout=10
            )
