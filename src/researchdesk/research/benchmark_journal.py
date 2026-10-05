"""Local, single-runner evaluation journal, separate from model-visible storage."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from researchdesk.agents.providers import ProviderError, ProviderTurn, ToolCall
from researchdesk.store import content_hash

from .benchmark_bundle import canonical_bytes


def private_directory(directory: Path):
    directory = directory.absolute()
    if any(parent.is_symlink() for parent in (directory, *directory.parents)):
        raise ValueError("Benchmark outputs cannot use symlink directories")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)


def private_file(path: Path):
    # Create with restrictive permissions before SQLite or provider data reaches it.
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


@contextmanager
def runner_lock(directory: Path):
    if directory.exists():
        allowed = {
            ".runner.lock",
            "journal.sqlite",
            "journal.sqlite-wal",
            "journal.sqlite-shm",
            "attempts",
        }
        if any(path.name not in allowed for path in directory.iterdir()):
            raise ValueError("Use a dedicated benchmark output directory")
    private_directory(directory)
    private_file(directory / ".runner.lock")
    with (directory / ".runner.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another benchmark runner owns this output directory") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Journal:
    """All methods require the caller's runner lock. Never shared with an agent."""

    def __init__(self, directory: Path):
        private_file(directory / "journal.sqlite")
        self.connection = sqlite3.connect(directory / "journal.sqlite", timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT);
            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL,
                case_id TEXT NOT NULL, arm TEXT NOT NULL, repetition INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned', started REAL, ended REAL, result TEXT
            );
            CREATE TABLE IF NOT EXISTS model_calls (
                attempt_id TEXT NOT NULL, task_id TEXT NOT NULL, turn INTEGER NOT NULL,
                request_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                started REAL NOT NULL, ended REAL, response TEXT, error_code TEXT,
                PRIMARY KEY (attempt_id, task_id, turn)
            );
            CREATE TABLE IF NOT EXISTS preflight (
                id INTEGER PRIMARY KEY, checked REAL NOT NULL, result TEXT NOT NULL
            );
            """
        )

    def close(self):
        self.connection.close()

    def initialize(self, *, binding: dict, manifest, protocol, split: str):
        selected_cases = [case for case in manifest.cases if case.split == split]
        if len(selected_cases) * len(protocol.arms) * protocol.repetitions > 10000:
            raise ValueError("A local pilot journal is limited to 10,000 planned attempts")
        encoded = canonical_bytes(binding).decode()
        with self.connection:
            row = self.connection.execute("SELECT value FROM binding WHERE id=1").fetchone()
            if row and row["value"] != encoded:
                raise ValueError("This output directory belongs to a different benchmark run")
            if row:
                return
            self.connection.execute("INSERT INTO binding VALUES (1, ?)", (encoded,))
            attempts = []
            for case in manifest.cases:
                if case.split != split:
                    continue
                for repetition in range(protocol.repetitions):
                    for arm in protocol.arms:
                        key = content_hash(
                            {
                                "binding": binding,
                                "case": case.case_id,
                                "arm": arm,
                                "rep": repetition,
                            }
                        )
                        attempts.append((key, case.case_id, arm, repetition))
            if not attempts:
                raise ValueError("The selected split contains no cases")
            # A fixed hash order interleaves arms without all baselines systematically first.
            for ordinal, (key, case_id, arm, repetition) in enumerate(sorted(attempts)):
                self.connection.execute(
                    "INSERT INTO attempts(id, ordinal, case_id, arm, repetition) VALUES(?,?,?,?,?)",
                    (key, ordinal, case_id, arm, repetition),
                )

    def attempts(self):
        rows = self.connection.execute("SELECT * FROM attempts ORDER BY ordinal").fetchall()
        return [
            dict(row) | {"result": json.loads(row["result"]) if row["result"] else None}
            for row in rows
        ]

    def start(self, attempt_id, now=None):
        now = time.time() if now is None else now
        with self.connection:
            self.connection.execute(
                "UPDATE attempts SET status='running', started=COALESCE(started,?) "
                "WHERE id=? AND status IN ('planned','running')",
                (now, attempt_id),
            )
        return next(item for item in self.attempts() if item["id"] == attempt_id)

    def finish(self, attempt_id, status, result):
        if status not in {"completed", "failed", "blocked"}:
            raise ValueError("Unknown terminal attempt status")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE attempts SET status=?, ended=?, result=? WHERE id=? AND status='running'",
                (status, time.time(), canonical_bytes(result).decode(), attempt_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only running attempts can receive an immutable final result")

    def preflight(self, result):
        with self.connection:
            self.connection.execute(
                "INSERT INTO preflight(checked,result) VALUES (?,?)",
                (time.time(), canonical_bytes(result).decode()),
            )

    def model_calls(self, attempt_id):
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM model_calls WHERE attempt_id=? ORDER BY started,task_id,turn",
                (attempt_id,),
            ).fetchall()
        ]


class MeteredProvider:
    """Count every request across child tasks; never silently retry an ambiguous call.

    A returned turn is durably cached before Runtime checkpoints its messages.
    A crash while a request is in flight leaves an indeterminate receipt; resume
    fails closed rather than spending again or fabricating the missing response.
    This cannot prove that a remote provider did not charge an errored request.
    """

    def __init__(self, provider, journal: Journal, attempt_id: str, max_calls: int):
        self.provider, self.journal = provider, journal
        self.attempt_id, self.max_calls = attempt_id, max_calls
        self.task_id: str | None = None

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        if self.task_id is None:
            raise ProviderError("benchmark_task_missing", "No benchmark task is bound")
        key = (self.attempt_id, self.task_id, sum(m["role"] == "assistant" for m in messages))
        request_hash = content_hash(
            {"messages": messages, "tools": tools, "instruction": instruction}
        )
        db = self.journal.connection
        row = db.execute(
            "SELECT * FROM model_calls WHERE attempt_id=? AND task_id=? AND turn=?", key
        ).fetchone()
        if row:
            if row["request_sha256"] != request_hash:
                raise ProviderError("benchmark_request_changed", "Resumed model request changed")
            if row["status"] == "completed":
                response = json.loads(row["response"])
                return ProviderTurn(
                    text=response["text"],
                    tool_calls=[ToolCall(**call) for call in response["tool_calls"]],
                    usage=response["usage"],
                    continuation=response["continuation"],
                )
            raise ProviderError(
                "benchmark_request_indeterminate",
                "A prior request failed or has an unknown outcome; it will not be retried",
            )
        if cancelled():
            raise ProviderError("cancelled", "Benchmark attempt was stopped")
        with db:
            count = db.execute(
                "SELECT COUNT(*) FROM model_calls WHERE attempt_id=?", (self.attempt_id,)
            ).fetchone()[0]
            if count >= self.max_calls:
                raise ProviderError("benchmark_model_budget", "Shared model-call budget exhausted")
            db.execute(
                "INSERT INTO model_calls(attempt_id,task_id,turn,request_sha256,status,started) "
                "VALUES(?,?,?,?,'inflight',?)",
                (*key, request_hash, time.time()),
            )
        try:
            turn = self.provider.complete(messages, tools, instruction, cancelled=cancelled)
            encoded = canonical_bytes(asdict(turn)).decode()
        except Exception as exc:
            # Provider failures are retained, but their text may contain private source data.
            code = exc.code if isinstance(exc, ProviderError) else "provider_failed"
            with db:
                db.execute(
                    "UPDATE model_calls SET status='failed',ended=?,error_code=? "
                    "WHERE attempt_id=? AND task_id=? AND turn=?",
                    (time.time(), code, *key),
                )
            raise ProviderError(code, "Provider request failed; its receipt was retained") from exc
        with db:
            db.execute(
                "UPDATE model_calls SET status='completed',ended=?,response=? "
                "WHERE attempt_id=? AND task_id=? AND turn=?",
                (time.time(), encoded, *key),
            )
        return turn
