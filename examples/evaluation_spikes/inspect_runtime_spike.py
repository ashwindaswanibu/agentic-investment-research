"""Synthetic Inspect compatibility spike, not an evaluation of model/clinical quality.

Install Inspect 0.3.276 and a copy of ResearchDesk into an isolated virtualenv.
Run from a clean directory: python inspect_runtime_spike.py --output /private/tmp/new-run
No model or data-provider network call is made. The real ResearchDesk Runtime,
ToolRegistry, artifact store, validation and request journal execute unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelOutput
from inspect_ai.solver import solver

from researchdesk.agents import ProviderError, ProviderTurn, ToolCall
from researchdesk.config import Settings
from researchdesk.research.benchmark_bundle import (
    canonical_bytes,
    freeze_bundle,
    implementation_sha256,
    load_bundle,
)
from researchdesk.research.benchmark_journal import Journal, private_directory, runner_lock
from researchdesk.research.benchmark_models import DatasetManifest
from researchdesk.research.benchmark_runner import _run_attempt, report
from researchdesk.store import Store, content_hash

VERSION = "0.3.276"
CASE_ID = "synthetic-inspect-case"
PRIVATE_TARGET = "SYNTHETIC_OPERATOR_TARGET_c64bf972_DO_NOT_FORWARD"
SOURCE_TEXT = (
    "SYNTHETIC engineering fixture. Fictional study SYNTHETIC-001 randomized "
    "40 fictional adults to Test A or Test B. The primary endpoint was fictional "
    "score change at week 12. No result or efficacy conclusion exists."
)
NETWORK_ATTEMPTS: list[dict] = []
PROVIDER_REQUESTS: dict[str, list[dict]] = {}
SOLVER_VISITS: list[dict] = []


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


@contextmanager
def no_python_tcp():
    """Defence for this pure-Python path, not a general OS egress guarantee."""
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def guarded(method):
        def call(sock, address):
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                NETWORK_ATTEMPTS.append({"operation": method.__name__, "address": str(address)})
                raise RuntimeError("Network connection forbidden in the synthetic spike")
            return method(sock, address)

        return call

    with (
        patch.object(socket.socket, "connect", guarded(connect)),
        patch.object(socket.socket, "connect_ex", guarded(connect_ex)),
    ):
        yield


def make_bundle(root):
    inputs = root / "input"
    blobs = inputs / "blobs"
    source = {"text": SOURCE_TEXT}
    reference = {"operator_only_sentinel": PRIVATE_TARGET, "synthetic": True}
    for value in (source, reference):
        write_json(blobs / f"{content_hash(value)}.json", value)
    manifest = DatasetManifest.model_validate(
        {
            "suite_id": "synthetic-inspect-compatibility",
            "version": "1",
            "created_at": "2026-10-05T12:00:00Z",
            "sources": [
                {
                    "source_id": "synthetic-public-evidence",
                    "version": "1",
                    "kind": "evidence",
                    "artifact_id": "package-source",
                    "artifact_sha256": content_hash(source),
                    "public_url": "https://example.org/synthetic-not-a-real-trial",
                    "acquired_at": "2026-10-05T11:00:00Z",
                },
                {
                    "source_id": "synthetic-programmatic-reference",
                    "version": "1",
                    "kind": "programmatic_reference",
                    "artifact_id": "package-private-reference-source",
                    "artifact_sha256": content_hash(reference),
                    "public_url": "https://example.org/synthetic-reference-only",
                    "acquired_at": "2026-10-05T11:00:00Z",
                },
            ],
            "cases": [
                {
                    "case_id": CASE_ID,
                    "question": "Describe the explicitly fictional study only.",
                    "issuer_ids": ["SYNTHETIC-ISSUER"],
                    "trial_family_ids": ["SYNTHETIC-FAMILY"],
                    "split": "development",
                    "source_ids": ["synthetic-public-evidence"],
                    "reference_id": "synthetic-operator-target",
                    "reference_sha256": content_hash(reference),
                    "reference_method": "programmatic",
                    "reference_source_ids": ["synthetic-programmatic-reference"],
                    "scope": "extraction_only",
                }
            ],
        }
    )
    # This generated reference is only an operator-side byte-leakage sentinel.
    # No scorer uses it and no clinical label/adjudication claim is made.
    protocol = {
        "protocol_id": "synthetic-inspect-adapter",
        "version": "1",
        "created_at": "2026-10-05T13:00:00Z",
        "dataset_manifest_sha256": manifest.sha256,
        "backend": "synthetic",
        "model": "deterministic-fixture-not-an-llm",
        "budget": {
            "max_tool_calls": 12,
            "max_model_calls": 10,
            "max_turns_per_task": 10,
            "max_output_tokens": 2000,
            "max_elapsed_seconds": 60,
        },
        "repetitions": 2,
        "common_instructions": "Use only supplied fictional evidence; this is an adapter test.",
        "fixed_specialist_instructions": {
            "researcher": "Inspect the fictional source.",
            "coder": "Compute only if necessary.",
            "reviewer": "Review fictional source attribution independently.",
        },
        "predeclared_metrics": ["Attempt identity, failure retention, store and target isolation."],
        "decision_limits": ["No model or clinical quality inference is permitted."],
        "stopping_criteria": ["Run all six registered synthetic attempts; retain the failure."],
    }
    write_json(inputs / "manifest.json", manifest.model_dump(mode="json"))
    write_json(inputs / "protocol.json", protocol)
    bundle = root / "bundle"
    freeze_bundle(
        manifest_path=inputs / "manifest.json",
        protocol_path=inputs / "protocol.json",
        blobs=blobs,
        output=bundle,
    )
    return bundle


def dossier(source):
    return {
        "intervention": "Test A",
        "indication": "Fictional condition",
        "population": "40 fictional adults",
        "trials": [
            {
                "trial_id": "SYNTHETIC-001",
                "design": {
                    "study_type": "interventional",
                    "allocation": "randomized",
                    "masking": "unknown",
                    "phase": "unknown",
                },
                "arms": [
                    {
                        "arm_id": "a",
                        "label": "Fictional test arm",
                        "intervention": "Test A",
                        "role": "treatment",
                        "planned_n": None,
                        "source_claim_ids": ["c1"],
                    }
                ],
                "endpoints": [
                    {
                        "endpoint_id": "primary",
                        "name": "Fictional score change",
                        "kind": "primary",
                        "timeframe": "Week 12",
                        "prespecified": "unknown",
                        "source_claim_ids": ["c1"],
                    }
                ],
                "source_claim_ids": ["c1"],
            }
        ],
        "claims": [
            {
                "id": "c1",
                "kind": "fact",
                "statement": SOURCE_TEXT,
                "trial_ids": ["SYNTHETIC-001"],
                "source_refs": [
                    {
                        "artifact_id": source["id"],
                        "artifact_sha256": source["sha256"],
                        "excerpt": SOURCE_TEXT,
                        "source_path": "/text",
                    }
                ],
            }
        ],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "No evidence search occurred beyond this synthetic fixture.",
        "missing_inputs": [
            {
                "field": "outcomes",
                "reason": "No result exists in the fixture.",
                "consequence": "No effect or forecast can be estimated.",
            }
        ],
        "uncertainty": ["All names and facts are fictional engineering inputs."],
        "forecast": {
            "status": "abstain",
            "target": "Fictional endpoint result",
            "as_of": "2026-10-05",
            "horizon": "2027-10-05",
            "outcome_rule": "A source would have to report the predefined endpoint.",
            "resolution_source": "No real resolution source exists.",
            "abstention_reason": "Synthetic fixtures cannot establish clinical evidence.",
        },
    }


class SyntheticProvider:
    """Scripted inputs only. Real Runtime/registry execution creates every tool result."""

    def __init__(self, attempt):
        self.attempt = attempt
        self.calls = 0

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        self.calls += 1
        request = {"messages": messages, "tools": tools, "instruction": instruction}
        # Snapshot the request before the runtime appends later messages.
        saved = json.loads(canonical_bytes(request))
        assert PRIVATE_TARGET not in json.dumps(saved)
        PROVIDER_REQUESTS.setdefault(self.attempt["id"], []).append(saved)
        advertised = {tool["name"] for tool in tools}
        assert "get_clinical_trial" not in advertised and "propose_paper_order" not in advertised
        assert ("delegate_task" in advertised) == (self.attempt["arm"] != "generalist")
        assert ("propose_specialist" in advertised) == (
            self.attempt["arm"] == "adaptive_specialists"
        )
        if self.calls == 1:
            source_id = json.loads(messages[0]["content"])["input_artifact_ids"][1]
            return ProviderTurn(
                tool_calls=[ToolCall("read-source", "read_artifact", {"artifact_id": source_id})]
            )
        if self.attempt["arm"] == "adaptive_specialists" and self.attempt["repetition"] == 1:
            raise ProviderError(
                "synthetic_failure", "Deliberate failure after one real tool result"
            )
        results = {m["name"]: m["content"]["data"] for m in messages if m["role"] == "tool"}
        if self.calls == 2:
            return ProviderTurn(
                tool_calls=[
                    ToolCall(
                        "dossier",
                        "submit_clinical_dossier",
                        {
                            "title": "Synthetic adapter-test dossier",
                            "dossier": dossier(results["read_artifact"]),
                        },
                    )
                ]
            )
        if self.calls == 3:
            receipt = results["submit_clinical_dossier"]
            return ProviderTurn(
                tool_calls=[
                    ToolCall(
                        "select",
                        "submit_benchmark_result",
                        {
                            "dossier_id": receipt["id"],
                            "dossier_sha256": receipt["sha256"],
                        },
                    )
                ]
            )
        return ProviderTurn("Selected the synthetic dossier. No clinical quality claim.")


@solver
def researchdesk_adapter(bundle_path: str, run_path: str):
    async def solve(state, generate):
        # Trusted adapter only: TaskState.target is accessible here. Never pass
        # TaskState, Sample metadata, target, or Inspect's history to the candidate.
        manifest, protocol, binding = load_bundle(Path(bundle_path))
        sample_id = str(state.sample_id)
        matching = [
            (c, arm)
            for c in manifest.cases
            for arm in protocol.arms
            if sample_id == f"{c.case_id}::{arm}"
        ]
        if len(matching) != 1 or not 1 <= state.epoch <= protocol.repetitions:
            raise ValueError("Unknown frozen case/arm/repetition identity")
        case, arm = matching[0]
        with runner_lock(Path(run_path)):
            journal = Journal(Path(run_path))
            try:
                journal.initialize(
                    binding={"bundle_sha256": binding["sha256"], "split": "development"},
                    manifest=manifest,
                    protocol=protocol,
                    split="development",
                )
                attempt = next(
                    a
                    for a in journal.attempts()
                    if a["case_id"] == case.case_id
                    and a["arm"] == arm
                    and a["repetition"] == state.epoch - 1
                )
                reused = attempt["status"] in {"completed", "failed", "blocked"}
                if not reused:
                    _run_attempt(
                        bundle_path=Path(bundle_path),
                        output=Path(run_path),
                        manifest=manifest,
                        protocol=protocol,
                        journal=journal,
                        attempt=attempt,
                        settings=Settings(
                            _env_file=None,
                            provider="disabled",
                            model="",
                            artifact_dir=Path(run_path) / "unused-artifacts",
                        ),
                        provider=SyntheticProvider(attempt),
                    )
                outcome = next(a for a in journal.attempts() if a["id"] == attempt["id"])
                identity = {
                    "case_id": case.case_id,
                    "arm": arm,
                    "repetition": state.epoch - 1,
                    "inspect_sample_id": sample_id,
                    "inspect_epoch": state.epoch,
                    "journal_attempt_id": attempt["id"],
                    "reused_terminal_receipt": reused,
                }
                SOLVER_VISITS.append(identity)
                state.metadata["researchdesk"] = {**identity, "outcome": outcome}
                state.output = ModelOutput.from_content(
                    "mockllm/no-generation", json.dumps(outcome)
                )
                state.completed = True
                if outcome["status"] != "completed":
                    raise RuntimeError("Retained ResearchDesk attempt failed: " + attempt["id"])
                return state
            finally:
                journal.close()

    return solve


@task
def synthetic_task(bundle_path: str, run_path: str):
    manifest, protocol, _ = load_bundle(Path(bundle_path))
    return Task(
        dataset=[
            Sample(id=f"{case.case_id}::{arm}", input=case.question, target=PRIVATE_TARGET)
            for case in manifest.cases
            for arm in protocol.arms
        ],
        solver=researchdesk_adapter(bundle_path, run_path),
        epochs=protocol.repetitions,
        fail_on_error=False,
        scorer=None,
        metadata={
            "synthetic": True,
            "clinical_quality_score": None,
            "purpose": "adapter feasibility",
        },
    )


def reconcile(log, root, expected_reused):
    snapshot = report(root / "run")
    registered = {(a["case_id"], a["arm"], a["repetition"]): a for a in snapshot["attempts"]}
    observed = []
    all_ids = set()
    all_sources = set()
    assert len(log.samples) == len(registered) == 6
    for sample in log.samples:
        identity = sample.metadata["researchdesk"]
        key = (identity["case_id"], identity["arm"], identity["repetition"])
        attempt = registered[key]
        assert identity["journal_attempt_id"] == attempt["id"]
        assert identity["reused_terminal_receipt"] is expected_reused
        assert sample.id == identity["inspect_sample_id"]
        assert sample.epoch == identity["inspect_epoch"] == attempt["repetition"] + 1
        assert sample.target == PRIVATE_TARGET  # Operator log retains its own target.
        assert bool(sample.error) == (attempt["status"] == "failed")
        store_path = root / "run" / "attempts" / attempt["id"] / "research.sqlite"
        store = Store(f"sqlite:///{store_path}")
        try:
            cases = store.list_cases()
            artifacts = store.list_artifacts()
            tasks = store.list_tasks()
            assert len(cases) == len(tasks) == 1
            assert cases[0]["id"] == attempt["result"]["case_id"]
            assert cases[0]["id"] not in all_ids
            all_ids.add(cases[0]["id"])
            sources = [a for a in artifacts if a["kind"] == "evidence"]
            assert len(sources) == 1 and sources[0]["id"] not in all_sources
            all_sources.add(sources[0]["id"])
            candidate_state = {
                "cases": cases,
                "artifacts": artifacts,
                "tasks": tasks,
                "messages": store.get_messages(tasks[0]["id"]),
                "tools": store.list_tool_calls(tasks[0]["id"]),
            }
            assert PRIVATE_TARGET not in json.dumps(candidate_state)
            assert not {"evaluation_reference", "evaluation_report"} & {
                a["kind"] for a in artifacts
            }
            selected = attempt["result"]["selected_dossier"]
            if selected:
                assert store.get_artifact(selected["id"])["sha256"] == selected["sha256"]
            observed.append(
                {
                    **identity,
                    "inspect_sample_uuid": sample.uuid,
                    "inspect_error": bool(sample.error),
                    "status": attempt["status"],
                    "case_store_id": cases[0]["id"],
                    "root_task_id": tasks[0]["id"],
                    "source_artifact_id": sources[0]["id"],
                    "source_sha256": sources[0]["sha256"],
                    "selected_dossier": selected,
                    "model_calls": attempt["result"]["model_calls"],
                    "tool_calls": attempt["result"]["tool_calls"],
                    "candidate_state_sha256": content_hash(candidate_state),
                }
            )
        finally:
            store.close()
    assert len({(a["case_id"], a["arm"], a["repetition"]) for a in observed}) == 6
    assert Counter(a["status"] for a in observed) == {"completed": 5, "failed": 1}
    return {
        "inspect_log_id": log.eval.eval_id,
        "inspect_run_id": log.eval.run_id,
        "inspect_status": log.status,
        "inspect_stats_model_usage": log.stats.model_usage,
        "inspect_sample_errors": sum(bool(s.error) for s in log.samples),
        "journal_statuses": snapshot["statuses"],
        "attempts": observed,
    }


def main(output):
    if importlib.metadata.version("inspect-ai") != VERSION:
        raise ValueError(f"This spike is pinned to Inspect {VERSION}")
    if output.exists():
        raise ValueError("Use a new output directory; retained observations cannot be overwritten")
    private_directory(output)
    os.environ["INSPECT_TRACE_FILE"] = str(output / "inspect-trace.log")
    bundle_path = make_bundle(output)
    run_path = output / "run"
    args = {
        "model": "mockllm/model",
        "max_samples": 1,
        "max_tasks": 1,
        "max_connections": 1,
        "retry_on_error": 0,
        "fail_on_error": False,
        "display": "none",
        "ctl_server": False,
        "log_format": "eval",
        "log_samples": True,
        "log_realtime": False,
        "log_model_api": False,
        "score": False,
        "checkpoint": False,
    }
    with no_python_tcp():
        first = eval(
            synthetic_task(str(bundle_path), str(run_path)),
            log_dir=str(output / "inspect-first"),
            **args,
        )[0]
        first = read_eval_log(first.location)
        first_report = reconcile(first, output, expected_reused=False)
        request_count = sum(map(len, PROVIDER_REQUESTS.values()))
        # Explicitly reschedule the same matrix; the adapter reuses terminal
        # receipts, including the failure. This is NOT Inspect eval_retry parity.
        second = eval(
            synthetic_task(str(bundle_path), str(run_path)),
            log_dir=str(output / "inspect-rescheduled"),
            **args,
        )[0]
        second = read_eval_log(second.location)
        second_report = reconcile(second, output, expected_reused=True)
        assert sum(map(len, PROVIDER_REQUESTS.values())) == request_count
    assert NETWORK_ATTEMPTS == []
    assert len(SOLVER_VISITS) == 12
    assert request_count == 22  # Five four-turn successes plus one two-turn failure.
    package_versions = sorted(
        (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
    )
    observed = {
        "synthetic": True,
        "clinical_quality_score": None,
        "model_quality_score": None,
        "inspect_version": VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "researchdesk_implementation_sha256": implementation_sha256(),
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "packages": package_versions,
        "first": first_report,
        "rescheduled": second_report,
        "synthetic_provider_requests": request_count,
        "python_tcp_attempts": NETWORK_ATTEMPTS,
        "request_hashes": {
            aid: [content_hash(r) for r in requests] for aid, requests in PROVIDER_REQUESTS.items()
        },
        "limitations": [
            "No remote provider, clinical grader or generated-code sandbox was exercised.",
            "Registry schemas were checked; delegation and profile creation were not exercised.",
            "Target isolation requires a trusted allowlisting adapter, not TaskState secrecy.",
            "Inspect usage is not ResearchDesk request usage; Agent Bridge capture was not tested.",
            "Terminal-attempt rescheduling was tested; eval_retry/eval_set and crashes were not.",
            "max_samples=1 and synchronous runtime call are deliberate serial spike constraints.",
        ],
    }
    write_json(output / "observed.json", observed)
    print(
        json.dumps(
            {
                "output": str(output),
                "inspect_version": VERSION,
                "planned_attempts": 6,
                "completed": 5,
                "failed": 1,
                "rescheduled_provider_calls": 0,
                "synthetic_provider_requests": request_count,
                "python_tcp_attempts": len(NETWORK_ATTEMPTS),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    # Inspect reads environment configuration; the documented clean launch below
    # runs in a temporary working directory with provider credentials absent.
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "RESEARCHDESK_OPENAI_API_KEY"):
        os.environ.pop(key, None)
    main(arguments.output.absolute())
