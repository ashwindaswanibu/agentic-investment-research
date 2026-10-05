"""Crash recovery fixtures: scripted model turns, synthetic sources, no live providers."""

import copy

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import update

from researchdesk.agents import ProviderTurn, Runtime, ToolCall, ToolContext, ToolRegistry
from researchdesk.agents.registry import TaskPolicy
from researchdesk.config import Settings
from researchdesk.db import ArtifactRow, TaskRow
from researchdesk.domain import ResearchTools
from researchdesk.errors import DomainError
from researchdesk.generated_tools import GeneratedResearchTools, ToolSpecification, ToolTests
from researchdesk.sandbox import SandboxResult
from researchdesk.store import Store


class ScriptedRecoveryProvider:
    """Explicit test fixture; never generates real research or production model output."""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.messages = []

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        self.messages.append(copy.deepcopy(messages))
        return next(self.turns)


class WorkerCrash(BaseException):
    """Simulate process death outside the runtime's recoverable Exception handler."""


class SourceInput(BaseModel):
    query: str = Field(min_length=1)


@pytest.fixture
def store(tmp_path):
    result = Store(f"sqlite:///{tmp_path / 'artifact-recovery.db'}")
    yield result
    result.close()


def expire_lease(store, task_id):
    with store.transaction() as session:
        session.execute(update(TaskRow).where(TaskRow.id == task_id).values(lease_until=0))


def source_registry(handler):
    registry = ToolRegistry()
    registry.register(
        "fetch_fixture_source",
        "Fetch a deliberately synthetic source fixture",
        SourceInput,
        {"researcher"},
        handler,
        side_effect="artifact",
    )
    return registry


def never_run(*args):
    raise AssertionError("Recovery must not call the changing external source again")


def seeded_effect(store, *, role="researcher", arguments=None):
    case = store.create_case("Recovery fixture", "Synthetic source can change between requests")
    task = store.create_task(case["id"], role, "Recover the committed source artifact")
    task = store.claim_task("original-worker")
    arguments = arguments if arguments is not None else {"query": "initial source"}
    call = ToolCall("interrupted-source", "fetch_fixture_source", arguments)
    store.save_messages(
        task["id"],
        [
            {"role": "user", "content": "Recovery test fixture"},
            ProviderTurn(tool_calls=[call]).message(),
        ],
        worker_id="original-worker",
    )
    store.begin_tool_call(
        task["id"], call.id, call.name, call.arguments, worker_id="original-worker"
    )
    artifact = store.put_artifact(
        case["id"],
        task["id"],
        "evidence",
        "Committed synthetic source",
        {"source": "synthetic engineering fixture", "revision": 1},
        idempotency_key=f"{task['id']}:{call.id}",
        worker_id="original-worker",
    )
    context = ToolContext(store, case["id"], task["id"], call.id, "original-worker", lambda: False)
    return case, task, call, artifact, context


def test_runtime_recovers_changing_source_after_artifact_commit_without_rerunning(
    store, monkeypatch
):
    case = store.create_case(
        "Crash fixture", "Changing source content must not be refetched", tool_budget=1
    )
    original = store.create_task(case["id"], "researcher", "Retain one changing source snapshot")
    attempts = []

    def changing_source(ctx, args):
        attempts.append(args.query)
        if len(attempts) > 1:
            raise RuntimeError("A refetch would return a changed source, not the original snapshot")
        return store.put_artifact(
            ctx.case_id,
            ctx.task_id,
            "evidence",
            "Synthetic source snapshot",
            {"query": args.query, "revision": 1},
            idempotency_key=ctx.idempotency_key,
            worker_id=ctx.worker_id,
        )

    registry = source_registry(changing_source)
    call = ToolCall("source-commit", "fetch_fixture_source", {"query": "first observation"})
    provider = ScriptedRecoveryProvider([ProviderTurn(tool_calls=[call])])

    def die_before_tool_completion(*args, **kwargs):
        raise WorkerCrash()

    with monkeypatch.context() as patch:
        patch.setattr(store, "finish_tool_call", die_before_tool_completion)
        with pytest.raises(WorkerCrash):
            Runtime(store, provider, registry, "original-worker").run_once()
    artifact = store.list_artifacts(case["id"])[0]
    assert store.list_tool_calls(task_id=original["id"])[0]["status"] == "running"
    assert store.get_task(original["id"])["status"] == "running"
    expire_lease(store, original["id"])
    replacement_provider = ScriptedRecoveryProvider(
        [ProviderTurn("Recovered the retained snapshot")]
    )
    completed = Runtime(store, replacement_provider, registry, "replacement-worker").run_once()
    assert completed["status"] == "completed"
    assert completed["attempt"] == 2
    assert attempts == ["first observation"]
    assert len(store.list_artifacts(case["id"])) == 1
    assert store.get_case(case["id"])["tool_calls_used"] == 1
    trace = store.list_tool_calls(task_id=original["id"])[0]
    assert trace["status"] == "completed"
    assert trace["result"]["data"]["id"] == artifact["id"]
    assert trace["result"]["data"]["sha256"] == artifact["sha256"]
    assert trace["result"]["data"]["content_included"] is False
    assert replacement_provider.messages[0][-1]["content"] == trace["result"]
    assert store.get_artifact(artifact["id"])["content"]["revision"] == 1


@pytest.mark.parametrize("change", ["arguments", "name"])
def test_recovery_requires_the_original_call_identity_and_arguments(store, change):
    _, task, call, _, ctx = seeded_effect(store)
    name = "another_tool" if change == "name" else call.name
    arguments = {"query": "new source"} if change == "arguments" else call.arguments
    with pytest.raises(DomainError) as error:
        store.recover_tool_artifact(task["id"], call.id, name, arguments, worker_id=ctx.worker_id)
    assert error.value.code == "CALL_CONFLICT"
    assert store.list_tool_calls(task_id=task["id"])[0]["status"] == "running"


def test_registry_does_not_treat_python_numeric_equality_as_identical_arguments(store):
    _, task, call, _, ctx = seeded_effect(store, arguments={"query": "source", "value": 1})
    with pytest.raises(DomainError) as error:
        store.recover_tool_artifact(
            task["id"],
            call.id,
            call.name,
            {"query": "source", "value": True},
            worker_id=ctx.worker_id,
        )
    assert error.value.code == "CALL_CONFLICT"


@pytest.mark.parametrize("ownership", ["task_id", "case_id"])
def test_recovery_rejects_an_artifact_with_wrong_ownership(store, ownership):
    case, task, call, artifact, ctx = seeded_effect(store)
    other_case = store.create_case("Other fixture", "This case does not own the committed output")
    other_task = store.create_task(other_case["id"], "researcher", "Unrelated producer task")
    replacement = other_task["id"] if ownership == "task_id" else other_case["id"]
    with store.transaction() as session:
        session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == artifact["id"])
            .values(**{ownership: replacement})
        )
    result = source_registry(never_run).execute(call.name, call.arguments, ctx)
    assert result["error"]["code"] == "ARTIFACT_TASK"
    assert store.get_case(case["id"])["tool_calls_used"] == 1
    assert store.list_tool_calls(task_id=task["id"])[0]["status"] == "running"


def test_expired_and_replaced_worker_cannot_recover_artifact(store):
    _, task, call, artifact, ctx = seeded_effect(store)
    expire_lease(store, task["id"])
    with pytest.raises(DomainError) as expired:
        store.recover_tool_artifact(
            task["id"], call.id, call.name, call.arguments, worker_id=ctx.worker_id
        )
    assert expired.value.code == "LEASE_LOST"
    claimed = store.claim_task("replacement-worker")
    assert claimed["id"] == task["id"]
    with pytest.raises(DomainError) as replaced:
        store.recover_tool_artifact(
            task["id"], call.id, call.name, call.arguments, worker_id=ctx.worker_id
        )
    assert replaced.value.code == "LEASE_LOST"
    recovered = store.recover_tool_artifact(
        task["id"],
        call.id,
        call.name,
        call.arguments,
        worker_id="replacement-worker",
    )
    assert recovered["id"] == artifact["id"]


def test_corrupt_committed_content_is_not_returned_as_success(store):
    _, task, call, artifact, ctx = seeded_effect(store)
    with store.transaction() as session:
        session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == artifact["id"])
            .values(content={"tampered": True})
        )
    result = source_registry(never_run).execute(call.name, call.arguments, ctx)
    assert result["error"]["code"] == "ARTIFACT_CORRUPT"
    assert store.list_tool_calls(task_id=task["id"])[0]["status"] == "running"


@pytest.mark.parametrize("kind", ["evaluation_reference", "evaluation_report"])
def test_protected_artifact_cannot_be_exfiltrated_through_recovery(store, kind):
    _, _, call, artifact, ctx = seeded_effect(store)
    with store.transaction() as session:
        session.execute(
            update(ArtifactRow).where(ArtifactRow.id == artifact["id"]).values(kind=kind)
        )
    result = source_registry(never_run).execute(call.name, call.arguments, ctx)
    assert result["error"]["code"] == "PROTECTED_EVALUATION"
    assert "data" not in result


@pytest.mark.parametrize("restriction", ["role", "profile", "input"])
def test_recovery_cannot_bypass_current_authorization_or_schema(store, restriction, monkeypatch):
    arguments = {"query": ""} if restriction == "input" else None
    role = "reviewer" if restriction == "role" else "researcher"
    _, _, call, _, ctx = seeded_effect(store, role=role, arguments=arguments)
    registry = source_registry(never_run)
    if restriction == "profile":
        # The profile resolver is an explicit policy fixture; activation validation
        # is covered by the specialist tests. This asserts dispatch ordering.
        registry.set_task_policy_resolver(lambda store, task: TaskPolicy(frozenset()))
    recovered = []
    original = store.recover_tool_artifact

    def observe_recovery(*args, **kwargs):
        recovered.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "recover_tool_artifact", observe_recovery)
    result = registry.execute(call.name, call.arguments, ctx)
    expected = {
        "role": "forbidden_tool",
        "profile": "specialist_tool_forbidden",
        "input": "invalid_arguments",
    }
    assert result["error"]["code"] == expected[restriction]
    assert not recovered
    assert "data" not in result


def test_recovered_qualification_gains_completed_trace_then_can_be_invoked(store, monkeypatch):
    case = store.create_case("Qualification recovery", "Synthetic functional-test recovery fixture")
    coder = store.create_task(case["id"], "coder", "Prepare a deterministic synthetic tool")
    coder = store.claim_task("coder-worker")
    research = ResearchTools(store, Settings(_env_file=None))
    generated = GeneratedResearchTools(research)
    source = "def run(payload):\n    return {'double': payload['value'] * 2}\n"
    code = store.put_artifact(
        case["id"], coder["id"], "code", "Synthetic arithmetic fixture", source
    )
    coder_ctx = ToolContext(store, case["id"], coder["id"], "define", "coder-worker", lambda: False)
    spec = generated.define(
        coder_ctx,
        ToolSpecification(
            name="double_integer",
            description="Double an integer in a synthetic functional fixture.",
            purpose="Test committed qualification recovery.",
            limitations="Arithmetic functionality only, not scientific validation.",
            input_fields=[
                {
                    "name": "value",
                    "type": "integer",
                    "required": True,
                    "description": "Integer input",
                }
            ],
            code_id=code["id"],
            code_sha256=code["sha256"],
        ),
    )
    reviewer = store.create_task(
        case["id"], "reviewer", "Independently test the fixture", parent_id=coder["id"]
    )
    reviewer = store.claim_task("review-worker")
    review_ctx = ToolContext(
        store, case["id"], reviewer["id"], "test-spec", "review-worker", lambda: False
    )
    tests = generated.tests(
        review_ctx,
        ToolTests(
            spec_id=spec["id"],
            spec_sha256=spec["sha256"],
            code_id=code["id"],
            code_sha256=code["sha256"],
            cases=[
                {"input": {"value": 2}, "expected": {"double": 4}},
                {"input": {"value": -3}, "expected": {"double": -6}},
            ],
        ),
    )

    class ScriptedSandboxFixture:
        """Test-only execution outcomes; never runs generated source on the host."""

        calls = 0
        forbid_execution = False

        def run(self, code, payload, **kwargs):
            self.calls += 1
            if self.forbid_execution:
                raise RuntimeError("Committed qualification must not execute again")
            return SandboxResult(True, {"double": payload["value"] * 2})

    sandbox = ScriptedSandboxFixture()
    research.sandbox = sandbox
    registry = research.registry()
    call = ToolCall(
        "qualify-once",
        "qualify_research_tool",
        {"tests_id": tests["id"], "tests_sha256": tests["sha256"]},
    )

    def crash(*args, **kwargs):
        raise WorkerCrash()

    with monkeypatch.context() as patch:
        patch.setattr(store, "finish_tool_call", crash)
        with pytest.raises(WorkerCrash):
            Runtime(
                store,
                ScriptedRecoveryProvider([ProviderTurn(tool_calls=[call])]),
                registry,
                "review-worker",
            ).run_task(reviewer)
    qualification = store.list_artifacts(case["id"], kind="research_tool_qualification")[0]
    assert qualification["content"]["status"] == "passed"
    assert sandbox.calls == 2
    sandbox.forbid_execution = True
    expire_lease(store, reviewer["id"])
    result = Runtime(
        store,
        ScriptedRecoveryProvider([ProviderTurn("Recovered independent qualification")]),
        registry,
        "replacement-worker",
    ).run_once()
    assert result["id"] == reviewer["id"] and result["status"] == "completed"
    assert sandbox.calls == 2
    trace = store.list_tool_calls(task_id=reviewer["id"])[0]
    assert trace["status"] == "completed"
    assert trace["result"]["data"]["id"] == qualification["id"]
    assert len(store.list_artifacts(case["id"], kind="research_tool_qualification")) == 1
    sandbox.forbid_execution = False
    researcher = store.create_task(
        case["id"], "researcher", "Reuse the recovered tool", parent_id=coder["id"]
    )
    invocation = ToolCall(
        "invoke-once",
        "invoke_research_tool",
        {
            "qualification_id": qualification["id"],
            "qualification_sha256": qualification["sha256"],
            "payload": {"value": 5},
        },
    )
    completed = Runtime(
        store,
        ScriptedRecoveryProvider(
            [ProviderTurn(tool_calls=[invocation]), ProviderTurn("Used the qualified fixture")]
        ),
        registry,
        "research-worker",
    ).run_once()
    assert completed["id"] == researcher["id"] and completed["status"] == "completed"
    output = store.list_artifacts(case["id"], kind="research_tool_result")[0]
    assert output["content"]["ok"] is True
    assert output["content"]["output"] == {"double": 10}
    assert sandbox.calls == 3
    assert store.get_case(case["id"])["tool_calls_used"] == 2
