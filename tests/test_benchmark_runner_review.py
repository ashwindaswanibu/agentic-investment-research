"""Independent failure-boundary checks using synthetic inputs and no remote model."""

import json
import os
import stat
import time
from types import SimpleNamespace

import pytest
from test_benchmark_bundle import inputs as inputs_fixture
from test_benchmark_runner import DossierScript, Scripted
from test_benchmark_runner import suite as suite_fixture
from test_research_quality import dossier as dossier_fixture
from test_research_quality import evidence as evidence_fixture

from researchdesk.agents import ProviderTurn
from researchdesk.config import Settings
from researchdesk.db import TaskRow
from researchdesk.domain import ResearchTools
from researchdesk.research import benchmark_runner as runner
from researchdesk.research.benchmark_bundle import canonical_bytes, freeze_bundle
from researchdesk.research.benchmark_journal import MeteredProvider
from researchdesk.store import Store

inputs = inputs_fixture
suite = suite_fixture
dossier = dossier_fixture
evidence = evidence_fixture


def test_on_time_completion_survives_crash_before_journal_commit(suite, dossier, monkeypatch):  # noqa: F811
    """Recovery time cannot rewrite the outcome of already committed work."""
    for claim in dossier["claims"]:
        for ref in claim["source_refs"]:
            ref["artifact_sha256"] = suite["manifest"].sources[0].artifact_sha256
    attempt = next(a for a in suite["journal"].attempts() if a["arm"] == "generalist")
    provider = DossierScript(dossier, "SYNTHETIC evidence: Test A compared with Test B.")

    def crash(*args, **kwargs):
        raise KeyboardInterrupt("Synthetic crash immediately before final journal commit")

    with monkeypatch.context() as patch:
        patch.setattr(suite["journal"], "finish", crash)
        with pytest.raises(KeyboardInterrupt):
            runner._run_attempt(**suite, attempt=attempt, provider=provider)
    interrupted = next(a for a in suite["journal"].attempts() if a["id"] == attempt["id"])
    assert interrupted["status"] == "running" and interrupted["result"] is None
    assert provider.calls == 3
    original_receipts = suite["journal"].model_calls(attempt["id"])
    deadline = interrupted["started"] + suite["protocol"].budget.max_elapsed_seconds
    recovery = Scripted([])
    with monkeypatch.context() as patch:
        patch.setattr(runner.time, "time", lambda: deadline + 100)
        runner._run_attempt(**suite, attempt=interrupted, provider=recovery)
    completed = next(a for a in suite["journal"].attempts() if a["id"] == attempt["id"])
    assert recovery.calls == 0
    assert completed["status"] == "completed"
    assert "benchmark_deadline" not in completed["result"]["error_codes"]
    assert completed["result"]["task_statuses"] == {"completed": 1}
    assert completed["result"]["selected_dossier"]["sha256"]
    assert suite["journal"].model_calls(attempt["id"]) == original_receipts
    assert len(suite["journal"].attempts()) == 6


@pytest.mark.parametrize("interruption", ["after_response", "inflight"])
def test_actual_runtime_recovery_never_repeats_provider_request(suite, monkeypatch, interruption):
    """Exercise the journal/runtime boundary, rather than only the cache in isolation."""
    store = Store(f"sqlite:///{suite['output'] / 'synthetic-recovery.sqlite'}")
    attempt = next(a for a in suite["journal"].attempts() if a["arm"] == "generalist")
    suite["journal"].start(attempt["id"])
    calls = []

    class FirstProvider:
        def complete(self, *args, **kwargs):
            calls.append("remote-request")
            if interruption == "inflight":
                raise KeyboardInterrupt("Synthetic interruption with unknown remote outcome")
            return ProviderTurn("Synthetic completed response", usage={"input_tokens": 1})

    try:
        record, root = runner._prepare(
            store,
            suite["bundle_path"],
            suite["manifest"],
            suite["protocol"],
            suite["manifest"].cases[0],
            attempt,
        )
        research = ResearchTools(store, suite["settings"])

        def runtime(provider, worker):
            return runner.BenchmarkRuntime(
                store,
                MeteredProvider(provider, suite["journal"], attempt["id"], 1),
                runner.benchmark_registry(research, "generalist", suite["protocol"]),
                worker_id=worker,
            )

        save_messages = store.save_messages

        def interrupt_checkpoint(task_id, messages, **kwargs):
            if any(message["role"] == "assistant" for message in messages):
                raise KeyboardInterrupt("Synthetic crash after cached response, before checkpoint")
            return save_messages(task_id, messages, **kwargs)

        with monkeypatch.context() as patch:
            if interruption == "after_response":
                patch.setattr(store, "save_messages", interrupt_checkpoint)
            with pytest.raises(KeyboardInterrupt):
                runtime(FirstProvider(), "lost-worker").run_once()
        first_receipt = suite["journal"].model_calls(attempt["id"])[0]
        assert first_receipt["status"] == (
            "completed" if interruption == "after_response" else "inflight"
        )
        assert store.get_task(root["id"])["status"] == "running"
        assert len(store.get_messages(root["id"])) == 1
        # Simulate expiration of the crashed process's real persisted lease.
        with store.transaction() as session:
            session.get(TaskRow, root["id"]).lease_until = time.time() - 1
        replacement = Scripted([])
        result = runtime(replacement, "replacement-worker").run_once()
        assert replacement.calls == 0 and calls == ["remote-request"]
        assert suite["journal"].model_calls(attempt["id"]) == [first_receipt]
        assert store.get_case(record["id"])["tool_calls_used"] == 0
        if interruption == "after_response":
            assert result["status"] == "completed"
            assert result["result"]["text"] == "Synthetic completed response"
        else:
            assert result["status"] == "failed"
            assert result["error"]["code"] == "benchmark_request_indeterminate"
    finally:
        store.close()


@pytest.fixture
def pilot(inputs, tmp_path, monkeypatch):  # noqa: F811
    """Real bundle and run files; deterministic provider and Docker discovery only."""
    protocol = json.loads(inputs["protocol_path"].read_text())
    protocol.update(backend="openai", model="synthetic-test-model")
    inputs["protocol_path"].write_bytes(canonical_bytes(protocol))
    freeze_bundle(**inputs)
    configurations = []

    def provider(configuration):
        configurations.append(configuration)
        return Scripted([ProviderTurn("Synthetic prose-only outcome")])

    monkeypatch.setattr(runner, "create_provider", provider)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"sha256:" + b"a" * 64),
    )
    settings = Settings(
        _env_file=None,
        provider="openai",
        model="synthetic-test-model",
        openai_api_key="synthetic-not-a-real-key",
        provider_timeout_seconds=120,
        artifact_dir=tmp_path / "artifacts",
    )
    return {
        "bundle_path": inputs["output"],
        "output": tmp_path / "private-run",
        "settings": settings,
        "split": "development",
    }, configurations


def test_effective_provider_timeout_change_is_rejected_before_another_attempt(pilot):
    arguments, configurations = pilot
    first = runner.run_suite(**arguments)
    with pytest.raises(ValueError, match="environment changed"):
        runner.run_suite(
            **{
                **arguments,
                "settings": arguments["settings"].model_copy(
                    update={"provider_timeout_seconds": 5}
                ),
            }
        )
    second = runner.report(arguments["output"])
    assert len(configurations) == 1 and configurations[0].timeout_seconds == 120
    assert second["statuses"] == first["statuses"]
    assert second["attempts"] == first["attempts"]


def test_timeout_settings_above_same_protocol_cap_are_equivalent(pilot):
    arguments, configurations = pilot
    first = runner.run_suite(
        **{
            **arguments,
            "settings": arguments["settings"].model_copy(update={"provider_timeout_seconds": 400}),
        }
    )
    second = runner.run_suite(
        **{
            **arguments,
            "settings": arguments["settings"].model_copy(update={"provider_timeout_seconds": 600}),
        }
    )
    assert [c.timeout_seconds for c in configurations] == [300, 300]
    assert first["statuses"] == {"failed": 1, "planned": 5}
    assert second["statuses"] == {"failed": 2, "planned": 4}


def test_output_files_are_owner_private_even_under_permissive_umask(pilot):
    arguments, _ = pilot
    prior_umask = os.umask(0)
    try:
        report = runner.run_suite(**arguments)
    finally:
        os.umask(prior_umask)
    output = arguments["output"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / ".runner.lock").stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "journal.sqlite").stat().st_mode) == 0o600
    attempted = next(a for a in report["attempts"] if a["status"] != "planned")
    directory = output / "attempts" / attempted["id"]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    database = directory / "research.sqlite"
    assert database.is_file() and stat.S_IMODE(database.stat().st_mode) == 0o600
    for path in output.rglob("*.sqlite-*"):
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_output_symlink_is_rejected_without_chmod_or_write_to_target(pilot):
    arguments, configurations = pilot
    target = arguments["output"].with_name("other-directory")
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    arguments["output"].symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        runner.run_suite(**arguments)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert list(target.iterdir()) == [] and configurations == []
