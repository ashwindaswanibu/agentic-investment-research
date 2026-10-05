"""Frozen-source clinical pilot runner with isolated attempts and retained failures.

This evaluates orchestration and attribution diagnostics, not clinical truth.
The first comparison varies delegation and reviewed profile adaptation. Generated
tool qualification and external retrieval are deliberately outside this protocol.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import sqlite3
import subprocess
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from researchdesk.agents import Runtime, create_provider, provider_health
from researchdesk.agents.registry import TaskPolicy, ToolError, ToolRegistry
from researchdesk.agents.runtime import TERMINAL
from researchdesk.agents.specialists import register_specialists
from researchdesk.api import provider_config
from researchdesk.domain import (
    ALL_ROLES,
    ArtifactRead,
    ArtifactWrite,
    BinaryComparison,
    Input,
    PythonInput,
    ResearchTools,
    ReviewInput,
    Search,
    _artifact_tool,
    artifact_ref,
)
from researchdesk.quality_workflow import DossierInput, save_dossier
from researchdesk.quant import compare_binary_rates
from researchdesk.research import CLINICAL_DOSSIER_GUIDANCE, parse_dossier
from researchdesk.source_navigation import InspectSourceInput, inspect_source
from researchdesk.store import Store, content_hash

from .benchmark_bundle import load_blob, load_bundle, load_public_scope
from .benchmark_journal import (
    Journal,
    MeteredProvider,
    private_directory,
    private_file,
    runner_lock,
)
from .benchmark_models import public_case_payload

CORE_TOOLS = frozenset(
    {
        "read_artifact",
        "inspect_source",
        "write_artifact",
        "search_library",
        "execute_python",
        "compare_binary_rates",
        "submit_clinical_dossier",
        "submit_benchmark_result",
    }
)


class Submission(Input):
    dossier_id: str = Field(min_length=1, max_length=200)
    dossier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BenchmarkRegistry(ToolRegistry):
    def __init__(self, arm, instructions):
        super().__init__()
        self.arm, self.instructions = arm, instructions
        self.scope = CORE_TOOLS
        if arm != "generalist":
            self.scope |= {"delegate_task", "review_artifact"}
        if arm == "adaptive_specialists":
            self.scope |= {"propose_specialist", "activate_specialist"}

    def task_policy(self, store, task):
        profile = super().task_policy(store, task)
        allowed = self.scope
        if profile.allowed_tools is not None:
            allowed &= profile.allowed_tools
        instructions = "\nFrozen benchmark: use only the supplied source versions. "
        instructions += (
            "No external retrieval, generated-tool qualification or trading is available."
        )
        if self.arm != "generalist" and task["role"] in self.instructions:
            instructions += "\n" + self.instructions[task["role"]]
        return TaskPolicy(frozenset(allowed), instructions + profile.instructions)


def benchmark_registry(research, arm, protocol):
    registry = BenchmarkRegistry(arm, protocol.fixed_specialist_instructions.model_dump())

    def write(context, arguments):
        # All arms have identical analysis-code authorship/execution capability.
        # This adapter exists only in isolated benchmark stores; production role
        # checks and independent review/admission handlers remain unchanged.
        sources = [
            research.artifact(identifier, case_id=context.case_id)
            for identifier in arguments.source_artifact_ids
        ]
        return research.save(
            context,
            arguments.kind,
            arguments.title,
            arguments.content,
            {"inputs": [artifact_ref(source) for source in sources], "execution_eligible": False},
        )

    def submit(context, arguments):
        task = context.store.get_task(context.task_id)
        if task["parent_id"] is not None:
            raise ToolError(
                "benchmark_root_required", "Only the root task selects the final dossier"
            )
        prior = _submissions(context.store, context.case_id)
        if prior:
            raise ToolError("benchmark_already_submitted", "The final selection is already frozen")
        dossier = research.artifact(
            arguments.dossier_id, kind="clinical_dossier", case_id=context.case_id
        )
        if dossier["sha256"] != arguments.dossier_sha256:
            raise ToolError("benchmark_hash_mismatch", "Select the exact persisted dossier version")
        parse_dossier(dossier["content"]["dossier"])
        return research.save(
            context,
            "note",
            "Frozen benchmark submission",
            arguments.model_dump(),
            {
                "benchmark_submission": True,
                "inputs": [artifact_ref(dossier)],
                "execution_eligible": False,
            },
        )

    specs = [
        (
            "inspect_source",
            "Navigate frozen evidence by JSON pointer; retain exact raw types and citations. "
            "Follow child/text cursors. Missing paths are not evidence of clinical absence.",
            InspectSourceInput,
            partial(inspect_source, research),
            "read",
            ALL_ROLES,
        ),
        (
            "read_artifact",
            "Read source/artifact content in pages; follow next_read to the end.",
            ArtifactRead,
            research.read,
            "read",
            ALL_ROLES,
        ),
        (
            "write_artifact",
            "Persist a note or Python code defining run(payload).",
            ArtifactWrite,
            write,
            "artifact",
            ALL_ROLES,
        ),
        (
            "search_library",
            "Search passages in this attempt's frozen sources and artifacts.",
            Search,
            research.search_tool,
            "read",
            ALL_ROLES,
        ),
        (
            "execute_python",
            "Run Python analysis in the pinned network-disabled sandbox.",
            PythonInput,
            research.python,
            "artifact",
            ALL_ROLES,
        ),
        (
            "compare_binary_rates",
            "Compute event-rate intervals; does not establish causality.",
            BinaryComparison,
            lambda c, a: compare_binary_rates(**a.model_dump()),
            "read",
            ALL_ROLES,
        ),
        (
            "submit_clinical_dossier",
            "Persist a dossier and its structural/attribution diagnostics; "
            "inspect before final selection.",
            DossierInput,
            partial(save_dossier, research),
            "artifact",
            ALL_ROLES,
        ),
        (
            "submit_benchmark_result",
            "Freeze exactly one final dossier ID/hash. This cannot be replaced; "
            "submit after all intended revisions.",
            Submission,
            submit,
            "artifact",
            {"coordinator"},
        ),
        (
            "review_artifact",
            "Independently review another task's exact artifact; "
            "review does not establish clinical truth.",
            ReviewInput,
            research.review,
            "artifact",
            {"reviewer"},
        ),
    ]
    for name, description, schema, handler, effect, roles in specs:
        registry.register(
            name,
            description,
            schema,
            roles,
            partial(_artifact_tool, handler) if effect == "artifact" else handler,
            side_effect=effect,
        )
    if arm == "adaptive_specialists":
        register_specialists(registry, research)
    return registry


def _submissions(store, case_id):
    return [
        a
        for a in store.list_artifacts(case_id, kind="note")
        if a["metadata"].get("benchmark_submission") is True
    ]


class BenchmarkRuntime(Runtime):
    def run_task(self, task):
        self.provider.task_id = task["id"]
        try:
            return super().run_task(task)
        finally:
            self.provider.task_id = None


def _prepare(store, bundle_path, manifest, protocol, case, attempt):
    record = store.create_case(
        f"Benchmark · {case.case_id}"[:200],
        case.question,
        tool_budget=protocol.budget.max_tool_calls,
        idempotency_key="benchmark-case",
    )
    public = public_case_payload(case, manifest)
    artifact_ids = []
    for source in public["sources"]:
        artifact = store.put_artifact(
            record["id"],
            None,
            "evidence",
            f"Frozen evidence · {source['source_id']}"[:200],
            load_blob(bundle_path / "blobs", source["artifact_sha256"]),
            {"frozen_source": source, "execution_eligible": False},
            idempotency_key=f"source:{source['source_id']}",
        )
        source["package_artifact_id"] = source["artifact_id"]
        source["artifact_id"] = artifact["id"]
        artifact_ids.append(artifact["id"])
    scope = load_public_scope(bundle_path / "blobs", manifest, protocol, case)
    if scope is not None:
        public["mechanical_scope"] = scope.model_dump(mode="json")
        public["mechanical_scope_sha256"] = scope.sha256
        public["mechanical_scope_instructions"] = (
            "This is guided registry extraction over the declared fields. Use the exact "
            "public trial, context and observation IDs and source locations; source_id maps "
            "to the attempt-local artifact_id in sources. Preserve required group and endpoint "
            "relationships. Unscored required fields may be unresolved; do not invent them. "
            "Additional observations cannot increase the scoped score and still need evidence. "
            "Source guidance removes discovery from this diagnostic; it does not measure "
            "clinical reasoning or investment skill."
        )
    briefing = store.put_artifact(
        record["id"],
        None,
        "note",
        "Frozen benchmark briefing",
        public,
        {"execution_eligible": False},
        idempotency_key="benchmark-briefing",
    )
    architecture = {
        "generalist": "Complete the research as a single agent. Delegation is unavailable.",
        "fixed_specialists": (
            "Delegate research, coding and review using the frozen role instructions. "
            "Dynamic profiles are unavailable."
        ),
        "adaptive_specialists": (
            "You may propose and independently review a specialized research profile when the "
            "evidence establishes a capability gap. Creation and review consume the shared "
            "budget; adaptation is optional."
        ),
    }[attempt["arm"]]
    instruction = (
        protocol.common_instructions
        + "\n"
        + architecture
        + "\n"
        + CLINICAL_DOSSIER_GUIDANCE
        + "\n"
        + "Read the briefing and supplied evidence using the input artifact IDs. "
        "Persist a clinical dossier, inspect its diagnostics, and select exactly one final version "
        "using submit_benchmark_result. A prose-only answer is not a completed evaluation. "
        "References are not available. Report conflicts and missing information explicitly. "
        "Do not infer clinical truth or trading value from a passing structural check. "
        + "Shared attempt budget: "
        + json.dumps(protocol.budget.model_dump())
    )
    root = store.create_task(
        record["id"],
        "coordinator",
        instruction,
        artifact_ids=[briefing["id"], *artifact_ids],
        idempotency_key="benchmark-root",
    )
    return record, root


def _outcome(store, record, root, journal, attempt, deadline):
    tasks = store.list_tasks(record["id"])
    submissions = _submissions(store, record["id"])
    calls = journal.model_calls(attempt["id"])
    pending = any(task["status"] not in TERMINAL for task in tasks)
    # A crash after durable task completion but before journal finalization must
    # not convert an on-time result to a timeout merely because recovery is later.
    terminal_at = (
        max(datetime.fromisoformat(task["finished_at"]).timestamp() for task in tasks)
        if tasks and not pending and all(task.get("finished_at") for task in tasks)
        else None
    )
    timed_out = (terminal_at if terminal_at is not None else time.time()) >= deadline
    selected = None
    if len(submissions) == 1:
        submission = store.get_artifact(submissions[0]["id"])
        selected = store.get_artifact(submission["content"]["dossier_id"])
        if selected["sha256"] != submission["content"]["dossier_sha256"]:
            raise ValueError("Final dossier binding failed integrity verification")
        timed_out |= datetime.fromisoformat(submission["created_at"]).timestamp() >= deadline
    if timed_out or pending:
        store.cancel_case(record["id"])
        tasks = store.list_tasks(record["id"])
    errors = [task["error"]["code"] for task in tasks if task.get("error")]
    if timed_out:
        errors.append("benchmark_deadline")
    if selected is None:
        errors.append("benchmark_missing_submission")
    all_completed = bool(tasks) and all(t["status"] == "completed" for t in tasks)
    if selected and all_completed and not timed_out:
        status = "completed"
    else:
        status = (
            "blocked"
            if timed_out or pending or any(t["status"] == "blocked" for t in tasks)
            else "failed"
        )
    usages = [json.loads(call["response"])["usage"] for call in calls if call["response"]]
    known_usage = sum(
        isinstance(usage, dict)
        and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("input_tokens", "output_tokens")
        )
        for usage in usages
    )
    return status, {
        "case_id": record["id"],
        "root_task_id": root["id"],
        "tasks_finished_epoch": terminal_at,
        "deadline_epoch": deadline,
        "task_statuses": dict(Counter(task["status"] for task in tasks)),
        "error_codes": sorted(set(errors)),
        "selected_dossier": artifact_ref(selected) if selected else None,
        "traceability_valid": selected["metadata"].get("traceability_valid") if selected else None,
        "model_calls": len(calls),
        "tool_calls": store.get_case(record["id"])["tool_calls_used"],
        "provider_usage": usages,
        "unreported_usage_calls": len(calls) - known_usage,
        "cost_usd": None,
        "clinical_quality_score": None,
        "limitations": [
            "Completion and traceability do not establish factual or clinical correctness.",
            "No scope-qualified reference grader is executed by this pilot runner.",
            "Elapsed deadline is an admission/cancellation cutoff; "
            "in-flight provider latency may overrun it.",
            "Provider aliases may change remotely even when the configured model string is frozen.",
        ],
    }


def _run_attempt(*, bundle_path, output, manifest, protocol, journal, attempt, settings, provider):
    private_directory(output / "attempts")
    directory = output / "attempts" / attempt["id"]
    private_directory(directory)
    private_file(directory / "research.sqlite")
    store = Store(f"sqlite:///{directory / 'research.sqlite'}")
    attempt = journal.start(attempt["id"])
    deadline = attempt["started"] + protocol.budget.max_elapsed_seconds
    try:
        case = next(item for item in manifest.cases if item.case_id == attempt["case_id"])
        record, root = _prepare(store, bundle_path, manifest, protocol, case, attempt)
        research = ResearchTools(store, settings.model_copy(update={"retrieval_mode": "lexical"}))
        metered = MeteredProvider(provider, journal, attempt["id"], protocol.budget.max_model_calls)
        runtime = BenchmarkRuntime(
            store,
            metered,
            benchmark_registry(research, attempt["arm"], protocol),
            worker_id=f"benchmark-{uuid4()}",
            max_turns=protocol.budget.max_turns_per_task,
            should_stop=lambda: time.time() >= deadline,
        )
        while time.time() < deadline:
            if runtime.run_once() is None:
                active = [t for t in store.list_tasks(record["id"]) if t["status"] not in TERMINAL]
                if not active:
                    break
                # An unexpired lease may belong to the prior process. Do not steal it.
                time.sleep(min(0.2, max(0, deadline - time.time())))
        status, result = _outcome(store, record, root, journal, attempt, deadline)
        journal.finish(attempt["id"], status, result)
    finally:
        store.close()


def _environment(settings, *, provider_timeout_seconds):
    image = subprocess.run(
        [settings.docker_binary, "image", "inspect", settings.sandbox_image, "--format", "{{.Id}}"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    digest = image.stdout.decode().strip()
    if image.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("A locally available sandbox image must be resolved before a pilot run")
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "sandbox_image": digest,
        "sandbox_timeout_seconds": settings.sandbox_timeout_seconds,
        "provider_timeout_seconds": provider_timeout_seconds,
        "retrieval_mode": "lexical",
        "packages_sha256": content_hash(
            sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
        ),
    }


def run_suite(*, bundle_path: Path, output: Path, split: str, settings, max_attempts: int = 1):
    if settings.read_only:
        raise ValueError("Read-only deployments cannot execute benchmark trials")
    if split not in {"development", "final"} or not 1 <= max_attempts <= 100:
        raise ValueError("Select a split and 1–100 attempts per invocation")
    manifest, protocol, binding = load_bundle(bundle_path)
    # Pilot diagnostics must not spend or expose a final holdout before the final
    # quality grader and independently adjudicated reference scope are qualified.
    if split != "development":
        raise ValueError("Final-set execution is not admitted by the diagnostic pilot runner")
    with runner_lock(output):
        journal = Journal(output)
        try:
            journal.initialize(
                binding={"bundle_sha256": binding["sha256"], "split": split},
                manifest=manifest,
                protocol=protocol,
                split=split,
            )
            configuration = provider_config(settings)
            if (configuration.provider, configuration.model) != (protocol.backend, protocol.model):
                raise ValueError("Configured provider/model must match the frozen protocol")
            if configuration.provider != "openai":
                raise ValueError(
                    "This pilot requires the adapter with an enforced output-token cap"
                )
            health = provider_health(configuration)
            journal.preflight(health)
            if not health["configured"]:
                return report(output)
            timeout = min(configuration.timeout_seconds, protocol.budget.max_elapsed_seconds)
            environment = _environment(settings, provider_timeout_seconds=timeout)
            prior = journal.connection.execute(
                "SELECT result FROM preflight ORDER BY id DESC"
            ).fetchall()
            environments = [
                json.loads(row["result"])["environment"]
                for row in prior
                if "environment" in json.loads(row["result"])
            ]
            if environments and any(env != environment for env in environments):
                raise ValueError("Execution environment changed; use a new run directory")
            journal.preflight({"environment": environment})
            settings = settings.model_copy(update={"sandbox_image": environment["sandbox_image"]})
            configuration = replace(
                configuration,
                max_output_tokens=protocol.budget.max_output_tokens,
                timeout_seconds=timeout,
            )
            count = 0
            for attempt in journal.attempts():
                if attempt["status"] not in {"planned", "running"}:
                    continue
                _run_attempt(
                    bundle_path=bundle_path,
                    output=output,
                    manifest=manifest,
                    protocol=protocol,
                    journal=journal,
                    attempt=attempt,
                    settings=settings,
                    provider=create_provider(configuration),
                )
                count += 1
                if count >= max_attempts:
                    break
            return report(output)
        finally:
            journal.close()


def report(output: Path):
    path = (output / "journal.sqlite").resolve()
    if not path.is_file():
        raise ValueError("No evaluation journal exists in this directory")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        attempts = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY ordinal")]
        for attempt in attempts:
            attempt["result"] = json.loads(attempt["result"]) if attempt["result"] else None
        return {
            "binding": json.loads(db.execute("SELECT value FROM binding WHERE id=1").fetchone()[0]),
            "planned_attempts": len(attempts),
            "statuses": dict(Counter(a["status"] for a in attempts)),
            "attempts": attempts,
            "preflight": [
                json.loads(row[0]) for row in db.execute("SELECT result FROM preflight ORDER BY id")
            ],
            "quality_claim": (
                "No clinical quality score or architecture superiority is established."
            ),
        }
    finally:
        db.close()
