"""No-network Docker execution for generated Python, without a host fallback."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class SandboxResult:
    ok: bool
    output: Any = None
    stdout: str = ""
    stderr: str = ""
    error: dict | None = None
    duration_ms: int = 0


# This program runs only inside the container. The payload is exactly the supplied
# history prefix; neither the full dataset nor any workspace is mounted.
_BOOTSTRAP = r"""
import json, resource, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (8*1024*1024, 8*1024*1024))
request = json.load(sys.stdin)
namespace = {"__name__": "generated_policy"}
exec(compile(request["code"], "<policy>", "exec"), namespace)
entrypoint = namespace.get("run")
if not callable(entrypoint):
    raise ValueError("Generated code must define run(payload)")
result = entrypoint(request["payload"])
print("\n__RESEARCHDESK_RESULT__=" + json.dumps(result, allow_nan=False))
"""


class DockerSandbox:
    def __init__(
        self,
        image: str = "python:3.12-slim",
        docker_binary: str = "docker",
        memory_mb: int = 128,
        cpus: float = 0.5,
        output_limit_bytes: int = 256_000,
    ):
        if memory_mb < 32 or memory_mb > 1024 or cpus <= 0 or cpus > 4:
            raise ValueError("Invalid sandbox resource limits")
        self.image, self.docker_binary = image, docker_binary
        self.memory_mb, self.cpus, self.output_limit_bytes = memory_mb, cpus, output_limit_bytes

    def availability(self) -> dict:
        binary = shutil.which(self.docker_binary)
        if not binary:
            return {
                "available": False,
                "reason": "Docker executable is unavailable; host execution is disabled.",
            }
        try:
            info = subprocess.run(
                [binary, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if info.returncode:
                return {
                    "available": False,
                    "reason": "Docker daemon is unavailable; host execution is disabled.",
                }
            image = subprocess.run(
                [binary, "image", "inspect", self.image, "--format", "{{.Id}}"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if image.returncode:
                return {"available": False, "reason": "Configured sandbox image is not installed."}
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "reason": "Docker readiness check failed."}
        return {
            "available": True,
            "reason": "Network-disabled, resource-limited Docker isolation is available.",
        }

    def cleanup_expired(self) -> dict:
        """Recover containers whose owning worker died before its timeout handler.

        Call only from the worker, never public readiness endpoints. The exact
        label, name prefix and absolute deadline prevent touching other workloads.
        """
        binary = shutil.which(self.docker_binary)
        if not binary:
            return {"removed": 0, "failed": 0, "reason": "Docker is unavailable."}
        try:
            listing = subprocess.run(
                [binary, "ps", "--all", "--quiet", "--filter", "label=researchdesk.sandbox=true"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if listing.returncode:
                return {"removed": 0, "failed": 1, "reason": "Docker cleanup lookup failed."}
            identifiers = listing.stdout.decode().split()[:100]
            identifiers = [item for item in identifiers if re.fullmatch(r"[a-f0-9]{12,64}", item)]
            if not identifiers:
                return {"removed": 0, "failed": 0}
            inspection = subprocess.run(
                [binary, "inspect", *identifiers], capture_output=True, timeout=5, check=False
            )
            if inspection.returncode:
                return {"removed": 0, "failed": 1, "reason": "Docker cleanup inspection failed."}
            expired = []
            for container in json.loads(inspection.stdout):
                labels = container.get("Config", {}).get("Labels") or {}
                if labels.get("researchdesk.sandbox") != "true":
                    continue
                if not container.get("Name", "").startswith("/researchdesk-"):
                    continue
                try:
                    deadline = float(labels.get("researchdesk.expires_at", "invalid"))
                except ValueError:
                    continue
                if deadline <= time.time():
                    expired.append(container["Id"])
            if not expired:
                return {"removed": 0, "failed": 0}
            removed = subprocess.run(
                [binary, "rm", "--force", *expired], capture_output=True, timeout=10, check=False
            )
            return {
                "removed": len(removed.stdout.decode().splitlines()),
                "failed": 0 if removed.returncode == 0 else 1,
            }
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {"removed": 0, "failed": 1, "reason": "Expired container cleanup failed."}

    def run(
        self,
        code: str,
        payload: dict,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        timeout_seconds: float = 15,
    ) -> SandboxResult:
        started = time.monotonic()

        def failure(code_: str, message: str, stdout: str = "", stderr: str = "") -> SandboxResult:
            return SandboxResult(
                False,
                stdout=stdout,
                stderr=stderr,
                error={"code": code_, "message": message},
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if cancelled():
            return failure("cancelled", "Execution was cancelled.")
        if (
            not isinstance(code, str)
            or len(code.encode()) > 200_000
            or not isinstance(payload, dict)
        ):
            return failure("invalid_input", "Expected code <=200 KB and a JSON object payload.")
        try:
            request = json.dumps({"code": code, "payload": payload}, allow_nan=False).encode()
        except (ValueError, TypeError):
            return failure("invalid_input", "Payload must contain finite JSON values.")
        if len(request) > 2_000_000 or timeout_seconds <= 0 or timeout_seconds > 120:
            return failure("invalid_input", "Input or execution time exceeds sandbox limits.")
        ready = self.availability()
        if not ready["available"]:
            return failure("sandbox_unavailable", ready["reason"])
        if cancelled():
            return failure("cancelled", "Execution was cancelled before container startup.")
        if time.monotonic() - started >= timeout_seconds:
            return failure(
                "sandbox_timeout", "Sandbox readiness exceeded the execution time limit."
            )
        binary = shutil.which(self.docker_binary)
        name = "researchdesk-" + uuid.uuid4().hex
        command = [
            binary,
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--label=researchdesk.sandbox=true",
            f"--label=researchdesk.expires_at={time.time() + timeout_seconds}",
            "--interactive",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            f"--memory={self.memory_mb}m",
            f"--memory-swap={self.memory_mb}m",
            f"--cpus={self.cpus}",
            "--pids-limit=32",
            "--ulimit=nofile=64:64",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            "--workdir=/tmp",
            self.image,
            "python",
            "-I",
            "-c",
            _BOOTSTRAP,
        ]
        with (
            tempfile.TemporaryFile() as stdin,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            stdin.write(request)
            stdin.seek(0)
            process = subprocess.Popen(
                command, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True
            )
            reason = None
            try:
                while process.poll() is None:
                    if cancelled():
                        reason = ("cancelled", "Execution was cancelled.")
                        break
                    if time.monotonic() - started > timeout_seconds:
                        reason = ("sandbox_timeout", "Generated code exceeded its time limit.")
                        break
                    if (
                        os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
                        > self.output_limit_bytes
                    ):
                        reason = (
                            "sandbox_output_limit",
                            "Generated code exceeded its output limit.",
                        )
                        break
                    time.sleep(0.05)
            finally:
                if process.poll() is None:
                    # Removing the container kills all its descendants, not just the CLI.
                    try:
                        subprocess.run(
                            [binary, "rm", "--force", name], capture_output=True, timeout=5
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    # A cancellation can race daemon-side container creation.
                    # Repeat cleanup after the client has stopped submitting work.
                    try:
                        subprocess.run(
                            [binary, "rm", "--force", name], capture_output=True, timeout=5
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(self.output_limit_bytes).decode(errors="replace")
            err = stderr.read(self.output_limit_bytes).decode(errors="replace")
            if reason:
                return failure(*reason, out, err)
            if (
                os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
                > self.output_limit_bytes
            ):
                return failure(
                    "sandbox_output_limit", "Generated code exceeded its output limit.", out, err
                )
            if process.returncode:
                return failure(
                    "sandbox_failed",
                    "Generated code failed inside its isolated container.",
                    out,
                    err,
                )
        marker = "__RESEARCHDESK_RESULT__="
        if marker not in out:
            return failure(
                "invalid_output", "Generated code did not return a JSON result.", out, err
            )
        logs, encoded = out.rsplit(marker, 1)
        try:
            output = json.loads(
                encoded.strip(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
            )
        except ValueError:
            return failure("invalid_output", "Generated code returned invalid JSON.", logs, err)
        return SandboxResult(
            True, output, logs.strip(), err, duration_ms=int((time.monotonic() - started) * 1000)
        )
