"""Qualify the built demo image with actual Docker, HTTP and process failures.

Run after building deploy/public-demo.Dockerfile. This needs no Python packages
outside the standard library and never calls a market or model provider.
"""

import argparse
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PYTHON = "/opt/venv/bin/python"
DATABASE = "/app/demo/researchdesk.db"


def docker(*args, timeout=40):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr[-4000:]}")
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


def inspect(name):
    return json.loads(docker("inspect", name))[0]


def request(base, path, *, body=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers
    )
    try:
        response = urllib.request.urlopen(req, timeout=45)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read()


def get_json(base, path):
    status, body = request(base, path)
    assert status == 200, (path, status, body[:500])
    return json.loads(body)


def wait_exit(name, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = inspect(name)["State"]
        if not state["Running"]:
            assert not state["OOMKilled"], state
            return state["ExitCode"]
        time.sleep(0.5)
    raise AssertionError(f"Container {name} did not exit within {timeout}s")


def wait_ready(name, base):
    started = time.monotonic()
    while time.monotonic() - started < 300:
        assert inspect(name)["State"]["Running"], docker("logs", name)[-6000:]
        try:
            health = get_json(base, "/api/health")
            if health.get("status") == "ok" and health.get("database") == "connected":
                return round(time.monotonic() - started, 3)
        except (OSError, ValueError, AssertionError):
            pass
        time.sleep(1)
    raise AssertionError("Combined frontend/API did not become ready within 300 seconds")


def run_check(image, output):
    receipt = {
        "checked_at": datetime.now(UTC).isoformat(),
        "image": image,
        "synthetic": True,
        "status": "failed",
        "checks": [],
        "limits": {"memory_bytes": 536870912, "cpus": 0.1, "swap_allowance_bytes": 0},
        "scope": "Finite container smoke and failure tests; not sustained load or Render hosting.",
    }
    containers = []

    def start(*extra):
        name = "researchdesk-demo-check-" + uuid4().hex[:12]
        containers.append(name)
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=0.1",
            "--read-only",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--publish=127.0.0.1::10000",
            *extra,
            image,
        )
        info = inspect(name)
        port = info["NetworkSettings"]["Ports"]["10000/tcp"][0]["HostPort"]
        return name, f"http://127.0.0.1:{port}"

    def inside(name, code):
        return docker("exec", name, PYTHON, "-c", code)

    def db_hash(name):
        return inside(
            name,
            f"import hashlib; print(hashlib.sha256(open('{DATABASE}','rb').read()).hexdigest())",
        )

    try:
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        name, base = start()
        receipt["startup_seconds"] = wait_ready(name, base)
        info = inspect(name)
        assert info["Config"]["User"] == "10001:10001"
        assert info["HostConfig"]["Memory"] == info["HostConfig"]["MemorySwap"] == 536870912
        assert info["HostConfig"]["NanoCpus"] == 100000000
        before = db_hash(name)
        capabilities = get_json(base, "/api/capabilities")
        assert capabilities["read_only"] is True
        assert capabilities["provider"]["configured"] is False
        assert capabilities["sandbox"]["available"] is False
        assert capabilities["worker"]["active"] is False
        assert capabilities["retrieval"] == {"mode": "lexical", "model": None}
        descriptor = get_json(base, "/api/demo")
        assert descriptor["synthetic"] is True and len(descriptor["walkthroughs"]) == 2
        status, html = request(base, "/demo")
        assert status == 200 and b"synthetic inputs" in html
        assets = set(re.findall(rb'(?:src|href)="(/_next/static/[^"?]+\.(?:js|css))', html))
        assert any(asset.endswith(b".css") for asset in assets)
        assert any(asset.endswith(b".js") for asset in assets)
        for asset in sorted(assets):
            status, payload = request(base, asset.decode())
            assert status == 200 and payload, asset
        receipt["static_assets_checked"] = len(assets)
        for walkthrough in descriptor["walkthroughs"]:
            href = walkthrough["href"]
            case_id = href.split("/")[2].split("?")[0]
            detail = get_json(base, f"/api/cases/{case_id}")
            assert not detail["tasks"] and not detail["tool_calls"]
            assert all(item["content"]["synthetic"] for item in detail["artifacts"])
            assert request(base, href)[0] == 200
            if walkthrough["id"] == "forecasts":
                assert len(get_json(base, f"/api/cases/{case_id}/forecasts")["items"]) == 5
        get_json(base, "/api/library?q=synthetic")
        assert get_json(base, "/api/paper/operations")["control"]["mode"] == "halted"
        for path in ("/api/cases", "/api/paper/account"):
            status, body = request(base, path, body={})
            assert status == 403 and json.loads(body)["error"]["code"] == "READ_ONLY", body
        inside(
            name,
            f"""
import errno, os, sqlite3
assert os.getuid() == 10001
assert os.stat('{DATABASE}').st_uid == 0
assert os.stat('{DATABASE}').st_mode & 0o222 == 0
try:
    fd = os.open('{DATABASE}', os.O_WRONLY)
except OSError as exc:
    assert exc.errno in (errno.EACCES, errno.EROFS), exc
else:
    os.close(fd)
    raise AssertionError('Package file unexpectedly writable')
# Match the application's URI. A plain WAL connection can fail creating its
# sidecars before attempting the statement; check an actual read before writing.
db = sqlite3.connect('file:{DATABASE}?mode=ro&immutable=1', uri=True)
assert db.execute('SELECT COUNT(*) FROM sqlite_schema').fetchone()[0] > 0
try:
    db.execute('CREATE TABLE forbidden (value TEXT)')
except sqlite3.OperationalError as exc:
    assert 'readonly' in str(exc).lower(), exc
else:
    raise AssertionError('Native database write unexpectedly succeeded')
finally:
    db.close()
""",
        )
        assert db_hash(name) == before
        docker("exec", name, PYTHON, "/app/deploy/public_demo_runtime.py", "health")
        metrics = json.loads(
            inside(
                name,
                """
import json
from pathlib import Path
root = Path('/sys/fs/cgroup')
print(json.dumps({
    'memory_peak_bytes': int((root/'memory.peak').read_text()),
    'memory_current_bytes': int((root/'memory.current').read_text()),
    'memory_events': dict(line.split() for line in (root/'memory.events').read_text().splitlines()),
}))
""",
            )
        )
        assert metrics["memory_peak_bytes"] < 536870912, metrics
        assert int(metrics["memory_events"]["oom"]) == 0, metrics
        assert int(metrics["memory_events"]["oom_kill"]) == 0, metrics
        receipt["memory"] = metrics
        receipt["checks"].extend(
            [
                "readonly_capabilities",
                "both_walkthroughs",
                "static_assets",
                "library_query",
                "api_mutations_denied",
                "native_sqlite_write_denied",
                "database_unchanged",
                "combined_health",
                "512mb_no_swap_no_oom",
            ]
        )
        docker("stop", "--time=20", name)
        assert wait_exit(name) in (0, 143)  # Clean exit or handled SIGTERM; never SIGKILL (137).
        receipt["checks"].append("graceful_sigterm")

        for child, executable_prefix in (("API", "python"), ("frontend", "node")):
            name, base = start()
            wait_ready(name, base)
            inside(
                name,
                f"""
import os, signal
from pathlib import Path
# Next changes its process title, so argv is not a reliable process identity.
# The image entrypoint is PID 1 and owns exactly these two direct children.
pids = Path('/proc/1/task/1/children').read_text().split()
matches = [int(pid) for pid in pids
           if Path(f'/proc/{{pid}}/exe').resolve().name.startswith({executable_prefix!r})]
assert len(matches) == 1, matches
os.kill(matches[0], signal.SIGKILL)
""",
            )
            assert wait_exit(name) != 0
            receipt["checks"].append(f"child_failure_exits:{child}")

        with tempfile.TemporaryDirectory(prefix="researchdesk-demo-bad-package-") as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            manifest.chmod(0o644)
            name, _ = start(
                "--mount", f"type=bind,source={manifest},target=/app/demo/manifest.json,readonly"
            )
            assert wait_exit(name, timeout=180) != 0
            assert "malformed" in docker("logs", name).lower()
            receipt["checks"].append("malformed_package_exits")
        receipt["status"] = "passed"
    except Exception as exc:
        receipt["error"] = str(exc)[:4000]
        receipt["container_logs"] = {}
        for name in containers:
            try:
                receipt["container_logs"][name] = docker("logs", name)[-6000:]
            except RuntimeError:
                pass
        raise
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_check(args.image, args.output)


if __name__ == "__main__":
    main()
