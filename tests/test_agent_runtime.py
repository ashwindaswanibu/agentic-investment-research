"""Deliberately scripted provider fixtures test orchestration, never production output."""

import json
import threading

import pytest
from pydantic import BaseModel

from researchdesk.agents import ProviderTurn, Runtime, ToolCall, ToolContext, ToolRegistry
from researchdesk.store import Store


class NoteArgs(BaseModel):
    text: str


class ScriptedProvider:
    """Unit-test fixture: explicit turns, not an application provider."""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.calls = []

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        self.calls.append(json.loads(json.dumps(messages)))
        return next(self.turns)


@pytest.fixture
def store(tmp_path):
    value = Store(f"sqlite:///{tmp_path / 'runtime.db'}")
    yield value
    value.close()


@pytest.fixture
def registry():
    result = ToolRegistry()

    def note(ctx, args):
        return ctx.store.put_artifact(
            ctx.case_id,
            ctx.task_id,
            "note",
            "Fixture note",
            {"text": args.text},
            idempotency_key=ctx.idempotency_key,
        )

    result.register(
        "write_note", "Save findings", NoteArgs, {"researcher", "coordinator"}, note, "artifact"
    )
    return result


def task(store, budget=10, role="researcher"):
    case = store.create_case("Fixture case", "A test hypothesis", tool_budget=budget)
    return store.create_task(case["id"], role, "Investigate this test hypothesis")


def test_tool_result_is_persisted_then_returned_to_model(store, registry):
    original = task(store)
    provider = ScriptedProvider(
        [
            ProviderTurn(tool_calls=[ToolCall("c1", "write_note", {"text": "Observed"})]),
            ProviderTurn("Saved evidence"),
        ]
    )
    result = Runtime(store, provider, registry, "w1").run_once()
    assert result["status"] == "completed"
    assert provider.calls[1][-1]["role"] == "tool"
    assert provider.calls[1][-1]["content"]["data"]["sha256"]
    assert store.list_tool_calls(task_id=original["id"])[0]["status"] == "completed"
    assert store.get_case(original["case_id"])["tool_calls_used"] == 1


def test_recovery_after_effect_commit_does_not_duplicate_artifact_or_budget(store, registry):
    original = task(store, budget=1)
    call = ToolCall("committed-before-crash", "write_note", {"text": "Retained"})
    store.save_messages(
        original["id"],
        [{"role": "user", "content": "test"}, ProviderTurn(tool_calls=[call]).message()],
    )
    store.begin_tool_call(original["id"], call.id, call.name, call.arguments)
    # Simulated crash after the idempotent mutation commits, before tool completion.
    store.put_artifact(
        original["case_id"],
        original["id"],
        "note",
        "Fixture note",
        {"text": "Retained"},
        idempotency_key=f"{original['id']}:{call.id}",
    )
    provider = ScriptedProvider([ProviderTurn("Recovered")])
    result = Runtime(store, provider, registry, "replacement").run_once()
    assert result["status"] == "completed"
    assert len(store.list_artifacts(original["case_id"])) == 1
    assert store.get_case(original["case_id"])["tool_calls_used"] == 1


def test_recovery_after_final_message_does_not_call_provider_again(store, registry):
    original = task(store)
    store.save_messages(original["id"], [ProviderTurn("Already completed").message()])
    provider = ScriptedProvider([])
    assert Runtime(store, provider, registry, "replacement").run_once()["status"] == "completed"
    assert not provider.calls


def test_budget_is_shared_by_all_calls_and_exhaustion_blocks(store, registry):
    original = task(store, budget=1)
    provider = ScriptedProvider(
        [
            ProviderTurn(
                tool_calls=[
                    ToolCall("c1", "write_note", {"text": "one"}),
                    ToolCall("c2", "write_note", {"text": "two"}),
                ]
            )
        ]
    )
    result = Runtime(store, provider, registry, "w").run_once()
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "BUDGET_EXHAUSTED"
    assert len(store.list_artifacts(original["case_id"])) == 1


def test_delegation_yields_parent_and_restores_child_results(store, registry):
    parent = task(store, role="coordinator")
    provider = ScriptedProvider(
        [
            ProviderTurn(
                tool_calls=[
                    ToolCall(
                        "delegate",
                        "delegate_task",
                        {
                            "role": "researcher",
                            "instruction": "Investigate a bounded claim",
                            "artifact_ids": [],
                        },
                    )
                ]
            ),
            ProviderTurn("Child found limitations"),
            ProviderTurn("Parent considered limitations"),
        ]
    )
    runtime = Runtime(store, provider, registry, "w")
    assert runtime.run_once()["status"] == "waiting"
    child_result = runtime.run_once()
    assert child_result["parent_id"] == parent["id"]
    assert child_result["status"] == "completed"
    result = runtime.run_once()
    assert result["id"] == parent["id"] and result["status"] == "completed"
    assert "Child found limitations" in provider.calls[-1][-1]["content"]
    assert len(store.list_tasks(parent["case_id"])) == 2


@pytest.mark.parametrize(
    "name,args,role,code",
    [
        ("missing", {}, "researcher", "unknown_tool"),
        ("write_note", {"text": "bad"}, "reviewer", "forbidden_tool"),
        (
            "write_note",
            {"text": "bad", "execute": "host command"},
            "researcher",
            "invalid_arguments",
        ),
        ("write_note", {}, "researcher", "invalid_arguments"),
        ("write_note", "not JSON", "researcher", "invalid_arguments"),
    ],
)
def test_registry_rejects_invalid_calls_without_side_effects(
    store, registry, name, args, role, code
):
    original = task(store, role=role)
    context = ToolContext(store, original["case_id"], original["id"], "fixture", "w", lambda: False)
    result = registry.execute(name, args, context)
    assert result["error"]["code"] == code
    assert not store.list_artifacts(original["case_id"])


def test_cancellation_after_model_returns_prevents_tool_execution(store, registry):
    original = task(store)

    class CancellingProvider:
        def complete(self, *args, **kwargs):
            store.cancel_case(original["case_id"])
            return ProviderTurn(
                tool_calls=[ToolCall("late", "write_note", {"text": "must not execute"})]
            )

    assert Runtime(store, CancellingProvider(), registry, "w").run_once()["status"] == "cancelled"
    assert not store.list_artifacts(original["case_id"])
    assert not store.list_tool_calls(task_id=original["id"])


def test_duplicate_provider_ids_cannot_replay_different_action(store, registry):
    original = task(store)
    provider = ScriptedProvider(
        [
            ProviderTurn(tool_calls=[ToolCall("reused", "write_note", {"text": "one"})]),
            ProviderTurn(tool_calls=[ToolCall("reused", "write_note", {"text": "different"})]),
        ]
    )
    result = Runtime(store, provider, registry, "w").run_once()
    assert result["status"] == "failed"
    assert result["error"]["code"] == "duplicate_call_id"
    assert len(store.list_artifacts(original["case_id"])) == 1


def test_lost_worker_cannot_save_response_or_execute_tool(store, registry):
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from researchdesk.db import TaskRow

    original = task(store)

    class LeaseStealingProvider:
        def complete(self, *args, **kwargs):
            with Session(store.engine) as session, session.begin():
                session.execute(
                    update(TaskRow)
                    .where(TaskRow.id == original["id"])
                    .values(worker_id="replacement")
                )
            return ProviderTurn(tool_calls=[ToolCall("late", "write_note", {"text": "unsafe"})])

    result = Runtime(store, LeaseStealingProvider(), registry, "expired-worker").run_once()
    assert result["worker_id"] == "replacement" and result["status"] == "running"
    assert not store.list_artifacts(original["case_id"])
    assert len(store.get_messages(original["id"])) == 1


def test_cancel_between_claim_and_first_checkpoint_terminalizes_task(store, registry):
    original = task(store)
    claimed = store.claim_task("w")
    store.cancel_case(original["case_id"])
    provider = ScriptedProvider([])
    result = Runtime(store, provider, registry, "w").run_task(claimed)
    assert result["status"] == "cancelled"
    assert not provider.calls


def test_parent_wake_is_atomic_and_cannot_reset_claimed_task(store, registry):
    parent = task(store, role="coordinator")
    child = store.create_task(
        parent["case_id"], "researcher", "Bounded child task", parent_id=parent["id"]
    )
    store.update_task(child["id"], status="completed", result={"text": "Test result"})
    store.update_task(parent["id"], status="waiting", checkpoint={"waiting_for": [child["id"]]})
    runtime = Runtime(store, ScriptedProvider([]), registry, "first-worker")
    assert runtime.resume_waiting() == 1
    claimed = store.claim_task("second-worker")
    assert claimed["id"] == parent["id"]
    assert not store.resume_task(parent["id"], [child["id"]], {"type": "stale_feedback"})
    current = store.get_task(parent["id"])
    assert current["status"] == "running" and current["worker_id"] == "second-worker"
    assert len(store.get_messages(parent["id"])) == 1


def test_worker_stop_requeues_and_replays_committed_effect_once(store):
    original = task(store, budget=1)
    stopping = threading.Event()
    registry = ToolRegistry()

    def commit_then_stop(ctx, args):
        artifact = ctx.store.put_artifact(
            ctx.case_id,
            ctx.task_id,
            "note",
            "Interrupted fixture",
            args.text,
            idempotency_key=ctx.idempotency_key,
            worker_id=ctx.worker_id,
        )
        stopping.set()
        return artifact

    registry.register("write_note", "Commit fixture", NoteArgs, {"researcher"}, commit_then_stop)
    first = Runtime(
        store,
        ScriptedProvider(
            [
                ProviderTurn(
                    tool_calls=[
                        ToolCall("interrupted", "write_note", {"text": "Committed before stop"})
                    ]
                )
            ]
        ),
        registry,
        "first",
        should_stop=stopping.is_set,
    ).run_once()
    assert first["status"] == "queued"
    assert store.list_tool_calls(task_id=original["id"])[0]["status"] == "running"
    second = Runtime(
        store,
        ScriptedProvider([ProviderTurn("Recovered committed effect")]),
        registry,
        "replacement",
    ).run_once()
    assert second["status"] == "completed"
    assert len(store.list_artifacts(original["case_id"])) == 1
    assert store.get_case(original["case_id"])["tool_calls_used"] == 1


def test_worker_stop_before_claim_preserves_queued_task(store, registry):
    original = task(store)
    assert (
        Runtime(store, ScriptedProvider([]), registry, "w", should_stop=lambda: True).run_once()
        is None
    )
    assert store.get_task(original["id"])["status"] == "queued"
