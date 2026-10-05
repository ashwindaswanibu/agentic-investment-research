"""Generated-tool gates using explicit synthetic fixtures and a real opt-in Docker check."""

import copy
import os
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from researchdesk.agents import ToolContext
from researchdesk.agents.registry import ToolError, ToolRegistry
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.generated_tools import (
    GeneratedResearchTools,
    InvocationInput,
    QualificationInput,
    ToolTests,
    register_generated_tools,
)
from researchdesk.sandbox import DockerSandbox, SandboxResult
from researchdesk.store import Store, content_hash

SOURCE = "def run(payload):\n    return {'double': payload['value'] * 2}\n"


class FixtureSandbox:
    """Observes requests; returns scripted fixture behavior without executing generated code."""

    def __init__(self):
        self.calls = []
        self.behavior = None

    def run(self, source, payload, **kwargs):
        assert source == SOURCE
        assert callable(kwargs["cancelled"])
        assert kwargs["timeout_seconds"] <= 20
        self.calls.append(copy.deepcopy(payload))
        if self.behavior:
            return self.behavior(payload)
        return SandboxResult(True, {"double": payload["value"] * 2})


class Environment:
    def __init__(self, path):
        self.store = Store(f"sqlite:///{path}")
        self.case = self.store.create_case(
            "Synthetic generated-tool fixture",
            "Test functionality and authorization boundaries",
            tool_budget=200,
        )
        self.sandbox = FixtureSandbox()
        self.research = ResearchTools(self.store, Settings(_env_file=None), self.sandbox)
        self.tools = GeneratedResearchTools(self.research)
        self.registry = register_generated_tools(ToolRegistry(), self.research)
        self.contexts = {}
        self.sequence = 0
        root = self.store.create_task(self.case["id"], "coordinator", "Test coordinator")
        self.root = root["id"]
        assert self.store.claim_task("fixture-worker")["id"] == self.root
        self.contexts["coordinator"] = self.context(root)
        for role in ("coder", "reviewer", "researcher"):
            task = self.store.create_task(self.case["id"], role, "Test task", parent_id=self.root)
            assert self.store.claim_task("fixture-worker")["id"] == task["id"]
            self.contexts[role] = self.context(task)
        self.code = self.store.put_artifact(
            self.case["id"],
            self.contexts["coder"].task_id,
            "code",
            "Synthetic doubling tool",
            SOURCE,
        )

    def context(self, task):
        return ToolContext(
            self.store, task["case_id"], task["id"], "unset", "fixture-worker", lambda: False
        )

    def call(self, role, name, arguments):
        self.sequence += 1
        ctx = replace(self.contexts[role], call_id=f"generated-fixture-{self.sequence}")
        row = self.store.begin_tool_call(
            ctx.task_id, ctx.call_id, name, arguments, worker_id=ctx.worker_id
        )
        result = self.registry.execute(name, arguments, ctx)
        self.store.finish_tool_call(
            row["id"],
            "completed" if result["ok"] else "failed",
            result=result,
            worker_id=ctx.worker_id,
        )
        return result

    def artifact_call(self, role, name, arguments):
        result = self.call(role, name, arguments)
        assert result["ok"], result
        assert result["data"]["content_included"] is False
        assert "content" not in result["data"]
        return self.store.get_artifact(result["data"]["id"])

    def specification(self):
        return self.artifact_call(
            "coder",
            "define_research_tool",
            {
                "name": "double_integer",
                "description": "Double a supplied integer for a synthetic functionality check.",
                "purpose": "A deterministic fixture for tool qualification.",
                "limitations": "Synthetic arithmetic only; no investment or scientific inference.",
                "input_fields": [
                    {
                        "name": "value",
                        "type": "integer",
                        "required": True,
                        "description": "Integer to double",
                    }
                ],
                "code_id": self.code["id"],
                "code_sha256": self.code["sha256"],
            },
        )

    def tests(self, spec):
        return self.artifact_call(
            "reviewer",
            "define_research_tool_tests",
            {
                "spec_id": spec["id"],
                "spec_sha256": spec["sha256"],
                "code_id": self.code["id"],
                "code_sha256": self.code["sha256"],
                "cases": [
                    {"input": {"value": 2}, "expected": {"double": 4}},
                    {"input": {"value": -3}, "expected": {"double": -6}},
                ],
            },
        )

    def qualification(self):
        spec = self.specification()
        tests = self.tests(spec)
        qualification = self.artifact_call(
            "reviewer",
            "qualify_research_tool",
            {
                "tests_id": tests["id"],
                "tests_sha256": tests["sha256"],
            },
        )
        return spec, tests, qualification

    def invocation(self, qualification, payload=None):
        return {
            "qualification_id": qualification["id"],
            "qualification_sha256": qualification["sha256"],
            "payload": {"value": 5} if payload is None else payload,
        }


@pytest.fixture
def env(tmp_path):
    fixture = Environment(tmp_path / "tools.db")
    yield fixture
    fixture.store.close()


def test_full_workflow_keeps_exact_provenance_and_compact_receipts(env):
    spec, tests, qualification = env.qualification()
    assert qualification["content"]["status"] == "passed"
    assert len(qualification["content"]["results"]) == 2
    result = env.artifact_call("researcher", "invoke_research_tool", env.invocation(qualification))
    assert result["content"]["output"] == {"double": 10}
    assert result["content"]["input"] == {"value": 5}
    assert result["content"]["input_sha256"] == content_hash({"value": 5})
    assert result["metadata"]["input_sha256"] == result["content"]["input_sha256"]
    assert result["metadata"]["execution_eligible"] is False
    assert result["metadata"]["scientific_validation"] is False
    assert {item["id"] for item in result["metadata"]["inputs"]} == {
        qualification["id"],
        spec["id"],
        tests["id"],
        env.code["id"],
    }
    assert env.sandbox.calls == [{"value": 2}, {"value": -3}, {"value": 5}]
    assert not env.store.list_artifacts(env.case["id"], kind="paper_intent")
    assert not env.store.list_artifacts(env.case["id"], kind="experiment")


def test_qualified_tool_can_be_reused_in_another_case(env):
    _, _, qualification = env.qualification()
    case = env.store.create_case(
        "Another research case", "Reuse a previously qualified computation"
    )
    task = env.store.create_task(case["id"], "researcher", "Reuse the tool")
    assert env.store.claim_task("fixture-worker")["id"] == task["id"]
    ctx = replace(env.context(task), call_id="cross-case-invocation")
    result = env.tools.invoke(ctx, InvocationInput(**env.invocation(qualification)))
    assert result["case_id"] == case["id"]
    assert result["content"]["output"] == {"double": 10}


def test_fabricated_qualification_without_completed_trace_is_rejected(env):
    _, _, original = env.qualification()
    forged = env.store.put_artifact(
        env.case["id"],
        original["task_id"],
        original["kind"],
        "Fabricated promotion",
        original["content"],
        original["metadata"],
    )
    before = len(env.sandbox.calls)
    result = env.call("researcher", "invoke_research_tool", env.invocation(forged))
    assert result["error"]["code"] == "unverified_qualification"
    assert len(env.sandbox.calls) == before


def test_running_qualification_trace_is_not_a_promotion(env):
    spec = env.specification()
    tests = env.tests(spec)
    ctx = replace(env.contexts["reviewer"], call_id="unfinished-qualification")
    args = QualificationInput(tests_id=tests["id"], tests_sha256=tests["sha256"])
    env.store.begin_tool_call(ctx.task_id, ctx.call_id, "qualify_research_tool", args.model_dump())
    artifact = env.tools.qualify(ctx, args)
    result = env.call("researcher", "invoke_research_tool", env.invocation(artifact))
    assert result["error"]["code"] == "unverified_qualification"
    assert "content" in artifact  # Direct methods return complete retained artifacts.


@pytest.mark.parametrize("field", ["qualification_sha256"])
def test_wrong_invocation_hash_blocks_execution(env, field):
    _, _, qualification = env.qualification()
    args = env.invocation(qualification)
    args[field] = "0" * 64
    result = env.call("researcher", "invoke_research_tool", args)
    assert result["error"]["code"] == "tool_hash_mismatch"
    assert len(env.sandbox.calls) == 2


@pytest.mark.parametrize("field", ["code_sha256", "spec_sha256"])
def test_qualification_cannot_bind_a_different_code_or_spec_hash(env, field):
    _, _, original = env.qualification()
    content = {**original["content"], field: "0" * 64}
    forged = env.store.put_artifact(
        env.case["id"],
        original["task_id"],
        original["kind"],
        "Wrong binding",
        content,
        original["metadata"],
    )
    result = env.call("researcher", "invoke_research_tool", env.invocation(forged))
    assert result["error"]["code"] == "tool_hash_mismatch"


def test_wrong_qualification_producer_is_rejected(env):
    _, _, original = env.qualification()
    forged = env.store.put_artifact(
        env.case["id"],
        env.contexts["coder"].task_id,
        original["kind"],
        "Wrong producer",
        original["content"],
        original["metadata"],
    )
    result = env.call("researcher", "invoke_research_tool", env.invocation(forged))
    assert result["error"]["code"] == "invalid_tool_producer"


def test_code_requires_a_coder_producer_and_cannot_be_manually_uploaded(env):
    spec = env.specification()
    for producer in (None, env.contexts["researcher"].task_id):
        code = env.store.put_artifact(env.case["id"], producer, "code", "Unqualified code", SOURCE)
        result = env.call(
            "coder",
            "define_research_tool",
            {
                **spec["content"],
                "code_id": code["id"],
                "code_sha256": code["sha256"],
            },
        )
        assert result["error"]["code"] == "invalid_tool_producer"


def test_role_boundaries_and_explicit_author_independence(env):
    spec = env.specification()
    tests = env.tests(spec)
    args = {"tests_id": tests["id"], "tests_sha256": tests["sha256"]}
    for role in ("coder", "researcher", "coordinator"):
        result = env.call(role, "qualify_research_tool", args)
        assert result["error"]["code"] == "forbidden_tool"
    with pytest.raises(ToolError, match="cannot qualify"):
        env.tools._independent(spec["task_id"], spec, env.code)
    with pytest.raises(ToolError, match="cannot qualify"):
        env.tools._independent(env.code["task_id"], spec, env.code)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"value": True},
        {"value": 2.0},
        {"value": "2"},
        {"value": None},
        {"value": 1, "extra": False},
        {"value": [2]},
    ],
)
def test_declared_inputs_are_strict_and_invalid_payloads_never_execute(env, payload):
    _, _, qualification = env.qualification()
    result = env.call("researcher", "invoke_research_tool", env.invocation(qualification, payload))
    assert result["error"]["code"] == "invalid_tool_input"
    assert len(env.sandbox.calls) == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "x" * 50_001])
def test_nonfinite_or_oversized_json_is_rejected_before_dispatch(value):
    with pytest.raises(ValidationError):
        InvocationInput(
            qualification_id="fixture", qualification_sha256="0" * 64, payload={"value": value}
        )


def test_test_cases_require_two_distinct_valid_inputs(env):
    spec = env.specification()
    tests = env.tests(spec)
    for cases in (tests["content"]["cases"][:1], [tests["content"]["cases"][0]] * 2):
        with pytest.raises(ValidationError):
            ToolTests(**{**tests["content"], "cases": cases})
    result = env.call(
        "reviewer",
        "define_research_tool_tests",
        {
            **tests["content"],
            "cases": [
                {"input": {"value": True}, "expected": {"double": 2}},
                {"input": {"value": 3}, "expected": {"double": 6}},
            ],
        },
    )
    assert result["error"]["code"] == "invalid_tool_input"


def test_partial_pass_records_every_outcome_without_promotion(env):
    env.sandbox.behavior = lambda payload: SandboxResult(
        True, {"double": 4 if payload["value"] == 2 else 999}
    )
    _, _, qualification = env.qualification()
    assert qualification["content"]["status"] == "failed"
    assert [row["passed"] for row in qualification["content"]["results"]] == [True, False]
    result = env.call("researcher", "invoke_research_tool", env.invocation(qualification))
    assert result["error"]["code"] == "tool_not_qualified"
    assert len(env.sandbox.calls) == 2


@pytest.mark.parametrize("mode", ["exception", "unavailable", "nonfinite", "bool_as_number"])
def test_sandbox_failures_and_inexact_json_are_retained_and_never_promoted(env, mode):
    def outcome(payload):
        if mode == "exception":
            raise RuntimeError("Private host details must not appear in retained errors")
        if mode == "unavailable":
            return SandboxResult(False, error={"code": "sandbox_unavailable"})
        if mode == "nonfinite":
            return SandboxResult(True, {"double": float("nan")})
        return SandboxResult(True, {"double": True})

    env.sandbox.behavior = outcome
    _, _, qualification = env.qualification()
    assert qualification["content"]["status"] == "failed"
    assert len(qualification["content"]["results"]) == 2
    assert all(not row["passed"] for row in qualification["content"]["results"])
    assert "Private host details" not in str(qualification)
    assert not env.call("researcher", "invoke_research_tool", env.invocation(qualification))["ok"]


def test_failed_invocation_retains_input_and_failure_without_fake_output(env):
    _, _, qualification = env.qualification()
    env.sandbox.behavior = lambda _: SandboxResult(False, error={"code": "sandbox_timeout"})
    result = env.artifact_call("researcher", "invoke_research_tool", env.invocation(qualification))
    assert result["content"]["ok"] is False
    assert result["content"]["error"]["code"] == "sandbox_timeout"
    assert "output" not in result["content"]
    assert result["content"]["input"] == {"value": 5}


def test_cancellation_prevents_execution_and_persistence(env):
    _, _, qualification = env.qualification()
    ctx = replace(env.contexts["researcher"], call_id="cancelled-call", cancelled=lambda: True)
    with pytest.raises(ToolError) as error:
        env.tools.invoke(ctx, InvocationInput(**env.invocation(qualification)))
    assert error.value.code == "cancelled"
    assert len(env.sandbox.calls) == 2
    assert not env.store.list_artifacts(env.case["id"], kind="research_tool_result")


@pytest.mark.sandbox
def test_real_docker_qualification_and_reusable_invocation(env):
    binary = os.environ.get("RESEARCHDESK_DOCKER_BINARY", "docker")
    if (
        binary == "docker"
        and Path("/Applications/Docker.app/Contents/Resources/bin/docker").exists()
    ):
        binary = "/Applications/Docker.app/Contents/Resources/bin/docker"
    sandbox = DockerSandbox(
        image=os.environ.get("RESEARCHDESK_SANDBOX_IMAGE", "researchdesk-sandbox:local"),
        docker_binary=binary,
    )
    readiness = sandbox.availability()
    if not readiness["available"]:
        pytest.skip(readiness["reason"])
    env.research.sandbox = sandbox
    _, _, qualification = env.qualification()
    assert qualification["content"]["status"] == "passed"
    result = env.artifact_call("researcher", "invoke_research_tool", env.invocation(qualification))
    assert result["content"]["output"] == {"double": 10}
