"""Independently tested, reusable analysis tools; never trading authorization.

Generated source executes only through the configured Docker sandbox. Test examples
establish declared functionality, not scientific validity or investment performance.
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from researchdesk.agents.registry import ToolError
from researchdesk.store import content_hash

MAX_JSON_BYTES = 50_000
KINDS = {
    "research_tool_spec",
    "research_tool_tests",
    "research_tool_qualification",
    "research_tool_result",
}


def _json(value: Any) -> str:
    """Canonical finite JSON with strict JSON types and a bounded nesting depth."""

    def check(item, depth=0):
        if depth > 32:
            raise ValueError("JSON nesting exceeds 32 levels.")
        if item is None or type(item) in {str, bool, int}:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise ValueError("Only finite JSON values with string object keys are supported.")

    check(value)
    result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(result.encode()) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds the 50,000-byte limit.")
    return result


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class InputField(Input):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    type: Literal["string", "number", "integer", "boolean"]
    required: bool = Field(strict=True)
    description: str = Field(min_length=1, max_length=500)


class ToolSpecification(Input):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    description: str = Field(min_length=10, max_length=1000)
    purpose: str = Field(min_length=10, max_length=2000)
    limitations: str = Field(min_length=10, max_length=4000)
    input_fields: list[InputField] = Field(min_length=1, max_length=16)
    code_id: str = Field(min_length=1, max_length=200)
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def unique_names(self):
        if len({item.name for item in self.input_fields}) != len(self.input_fields):
            raise ValueError("Input field names must be unique.")
        return self


class TestExample(Input):
    input: dict[str, Any]
    expected: Any

    @model_validator(mode="after")
    def finite_bounded_json(self):
        _json(self.input)
        _json(self.expected)
        return self


class ToolTests(Input):
    spec_id: str = Field(min_length=1, max_length=200)
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_id: str = Field(min_length=1, max_length=200)
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cases: list[TestExample] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def distinct_inputs(self):
        if len({_json(case.input) for case in self.cases}) != len(self.cases):
            raise ValueError("Test inputs must be distinct; provide at least two cases.")
        return self


class QualificationInput(Input):
    tests_id: str = Field(min_length=1, max_length=200)
    tests_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class InvocationInput(Input):
    qualification_id: str = Field(min_length=1, max_length=200)
    qualification_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict[str, Any]

    @model_validator(mode="after")
    def finite_bounded_json(self):
        _json(self.payload)
        return self


def _ref(artifact):
    return {key: artifact[key] for key in ("id", "kind", "title", "sha256")}


def _validate_payload(specification, payload):
    try:
        _json(payload)
    except (ValueError, TypeError) as exc:
        raise ToolError("invalid_tool_input", str(exc)) from exc
    fields = {field.name: field for field in specification.input_fields}
    if set(payload) - fields.keys():
        raise ToolError("invalid_tool_input", "Undeclared input fields are forbidden.")
    for name, field in fields.items():
        if name not in payload:
            if field.required:
                raise ToolError("invalid_tool_input", f"Required input field is missing: {name}.")
            continue
        expected = {
            "string": {str},
            "number": {int, float},
            "integer": {int},
            "boolean": {bool},
        }[field.type]
        if type(payload[name]) not in expected:
            raise ToolError("invalid_tool_input", f"Input field {name} must be {field.type}.")


class GeneratedResearchTools:
    def __init__(self, research):
        self.research = research
        self.store = research.store

    def _role(self, ctx, allowed):
        ctx.check_cancelled()
        task = self.store.get_task(ctx.task_id)
        if task["case_id"] != ctx.case_id or task["role"] not in allowed:
            raise ToolError("forbidden_tool", "This task cannot perform this research-tool step.")

    def _producer(self, artifact, role):
        if not artifact["task_id"]:
            raise ToolError("invalid_tool_producer", "The artifact needs an attributable task.")
        task = self.store.get_task(artifact["task_id"])
        if task["role"] != role or task["case_id"] != artifact["case_id"]:
            raise ToolError("invalid_tool_producer", f"This artifact requires a {role} producer.")

    def _artifact(self, identifier, kind, digest, case_id=None):
        artifact = self.research.artifact(identifier, kind=kind, case_id=case_id)
        if artifact["sha256"] != digest:
            raise ToolError("tool_hash_mismatch", "The exact inspected artifact hash is required.")
        return artifact

    def _spec(self, identifier, digest, case_id=None):
        spec = self._artifact(identifier, "research_tool_spec", digest, case_id)
        self._producer(spec, "coder")
        args = ToolSpecification.model_validate(spec["content"])
        code = self._artifact(args.code_id, "code", args.code_sha256, spec["case_id"])
        self._producer(code, "coder")
        if not isinstance(code["content"], str) or len(code["content"].encode()) > 100_000:
            raise ToolError("invalid_tool_code", "Provide Python source of at most 100 KB.")
        return spec, code, args

    @staticmethod
    def _independent(task_id, spec, code):
        if task_id in {spec["task_id"], code["task_id"]}:
            raise ToolError(
                "independent_review_required", "Tool authors cannot qualify their work."
            )

    def define(self, ctx, args: ToolSpecification):
        self._role(ctx, {"coder"})
        code = self._artifact(args.code_id, "code", args.code_sha256, ctx.case_id)
        self._producer(code, "coder")
        if not isinstance(code["content"], str) or len(code["content"].encode()) > 100_000:
            raise ToolError("invalid_tool_code", "Provide Python source of at most 100 KB.")
        return self.research.save(
            ctx,
            "research_tool_spec",
            f"Research tool · {args.name}",
            args.model_dump(),
            {"inputs": [_ref(code)], "execution_eligible": False},
        )

    def tests(self, ctx, args: ToolTests):
        self._role(ctx, {"reviewer"})
        spec, code, specification = self._spec(args.spec_id, args.spec_sha256, ctx.case_id)
        self._independent(ctx.task_id, spec, code)
        if args.code_id != code["id"] or args.code_sha256 != code["sha256"]:
            raise ToolError("tool_hash_mismatch", "Tests must bind the specification's exact code.")
        for example in args.cases:
            _validate_payload(specification, example.input)
        return self.research.save(
            ctx,
            "research_tool_tests",
            f"Functional tests · {specification.name}",
            args.model_dump(),
            {"inputs": [_ref(spec), _ref(code)], "execution_eligible": False},
        )

    def _tests(self, identifier, digest, case_id=None):
        tests = self._artifact(identifier, "research_tool_tests", digest, case_id)
        self._producer(tests, "reviewer")
        args = ToolTests.model_validate(tests["content"])
        spec, code, specification = self._spec(args.spec_id, args.spec_sha256, tests["case_id"])
        self._independent(tests["task_id"], spec, code)
        if args.code_id != code["id"] or args.code_sha256 != code["sha256"]:
            raise ToolError("tool_hash_mismatch", "Tests do not bind this exact code artifact.")
        for example in args.cases:
            _validate_payload(specification, example.input)
        return tests, spec, code, specification, args

    def _run(self, ctx, code, payload):
        ctx.check_cancelled()
        try:
            result = self.research.sandbox.run(
                code["content"],
                payload,
                cancelled=ctx.cancelled,
                timeout_seconds=min(self.research.settings.sandbox_timeout_seconds, 20),
            )
            if not result.ok:
                outcome = {"ok": False, "error": result.error or {"code": "sandbox_failed"}}
            else:
                _json(result.output)
                outcome = {"ok": True, "output": result.output}
        except Exception:
            # Never leak host exception details into a generated result or run on the host.
            outcome = {
                "ok": False,
                "error": {"code": "sandbox_exception", "message": "Isolated execution failed."},
            }
        ctx.check_cancelled()
        return outcome

    def qualify(self, ctx, args: QualificationInput):
        self._role(ctx, {"reviewer"})
        tests, spec, code, specification, examples = self._tests(
            args.tests_id, args.tests_sha256, ctx.case_id
        )
        self._independent(ctx.task_id, spec, code)
        results = []
        for example in examples.cases:
            outcome = self._run(ctx, code, example.input)
            matched = outcome["ok"] and _json(outcome["output"]) == _json(example.expected)
            results.append(
                {
                    "input_sha256": content_hash(example.input),
                    "expected_sha256": content_hash(example.expected),
                    "passed": matched,
                    **outcome,
                }
            )
        passed = all(row["passed"] for row in results)
        return self.research.save(
            ctx,
            "research_tool_qualification",
            f"{'Passed' if passed else 'Failed'} · {specification.name}",
            {
                "status": "passed" if passed else "failed",
                "spec_id": spec["id"],
                "spec_sha256": spec["sha256"],
                "code_id": code["id"],
                "code_sha256": code["sha256"],
                **args.model_dump(),
                "results": results,
                "limitations": "Functional examples do not establish scientific truth or alpha.",
            },
            {
                "inputs": [_ref(spec), _ref(code), _ref(tests)],
                "qualification_call_id": ctx.call_id,
                "execution_eligible": False,
            },
        )

    def _qualified(self, args):
        qualification = self._artifact(
            args.qualification_id, "research_tool_qualification", args.qualification_sha256
        )
        self._producer(qualification, "reviewer")
        content = qualification["content"]
        if not isinstance(content, dict) or content.get("status") != "passed":
            raise ToolError("tool_not_qualified", "All independent functional tests must pass.")
        tests, spec, code, specification, examples = self._tests(
            content.get("tests_id"), content.get("tests_sha256"), qualification["case_id"]
        )
        self._independent(qualification["task_id"], spec, code)
        for name, artifact in (("spec", spec), ("code", code)):
            if (
                content.get(name + "_id") != artifact["id"]
                or content.get(name + "_sha256") != artifact["sha256"]
            ):
                raise ToolError("tool_hash_mismatch", "Qualification input bindings are invalid.")
        rows = content.get("results")
        if not isinstance(rows, list) or len(rows) != len(examples.cases):
            raise ToolError("tool_not_qualified", "Qualification must retain every test outcome.")
        for row, example in zip(rows, examples.cases, strict=True):
            if (
                not isinstance(row, dict)
                or row.get("passed") is not True
                or row.get("ok") is not True
                or row.get("input_sha256") != content_hash(example.input)
                or row.get("expected_sha256") != content_hash(example.expected)
                or _json(row.get("output")) != _json(example.expected)
            ):
                raise ToolError("tool_not_qualified", "Qualification contains an invalid outcome.")
        # A prose artifact or an untracked direct Store write is not a computed promotion.
        calls = self.store.list_tool_calls(task_id=qualification["task_id"])
        call_id = qualification["metadata"].get("qualification_call_id")
        recorded = any(
            call["call_id"] == call_id
            and call["name"] == "qualify_research_tool"
            and call["status"] == "completed"
            and call["arguments"] == {"tests_id": tests["id"], "tests_sha256": tests["sha256"]}
            and isinstance(call.get("result"), dict)
            and call["result"].get("ok") is True
            and isinstance(call["result"].get("data"), dict)
            and call["result"]["data"].get("id") == qualification["id"]
            and call["result"]["data"].get("sha256") == qualification["sha256"]
            for call in calls
        )
        if not recorded:
            raise ToolError(
                "unverified_qualification", "A completed qualification trace is required."
            )
        return qualification, tests, spec, code, specification

    def invoke(self, ctx, args: InvocationInput):
        self._role(ctx, {"researcher", "coder", "coordinator"})
        qualification, tests, spec, code, specification = self._qualified(args)
        _validate_payload(specification, args.payload)
        outcome = self._run(ctx, code, args.payload)
        return self.research.save(
            ctx,
            "research_tool_result",
            f"Research tool result · {specification.name}",
            {
                "tool_name": specification.name,
                "input": args.payload,
                "input_sha256": content_hash(args.payload),
                **outcome,
                "limitations": specification.limitations,
            },
            {
                "inputs": [_ref(qualification), _ref(spec), _ref(code), _ref(tests)],
                "input_sha256": content_hash(args.payload),
                "execution_eligible": False,
                "scientific_validation": False,
            },
        )


def register_generated_tools(registry, research):
    """Register fixed, role-scoped handlers, not generated code as host callables."""
    from researchdesk.domain import compact_artifact

    tools = GeneratedResearchTools(research)
    definitions = [
        (
            "define_research_tool",
            "Define a reusable analysis tool from a coder's immutable run(payload) artifact. "
            "Declare scalar inputs, purpose and limitations; qualification is still required.",
            ToolSpecification,
            {"coder"},
            tools.define,
        ),
        (
            "define_research_tool_tests",
            "Independently specify 2–8 distinct input/expected-JSON examples for exact tool/code "
            "hashes. These assert functionality, not scientific validity.",
            ToolTests,
            {"reviewer"},
            tools.tests,
        ),
        (
            "qualify_research_tool",
            "Run every independent example in isolated Docker. All must match exact finite JSON; "
            "failed tests never qualify a tool or authorize trading.",
            QualificationInput,
            {"reviewer"},
            tools.qualify,
        ),
        (
            "invoke_research_tool",
            "Invoke an exact qualified reusable analysis tool in isolated Docker with declared "
            "scalar inputs (50 KB maximum). Its output grants no strategy or trading privileges.",
            InvocationInput,
            {"researcher", "coder", "coordinator"},
            tools.invoke,
        ),
    ]
    for name, description, schema, roles, handler in definitions:

        def receipt(ctx, args, handler=handler):
            return compact_artifact(handler(ctx, args))

        registry.register(
            name,
            description + " Returns a compact receipt; read_artifact inspects full content.",
            schema,
            roles,
            receipt,
            side_effect="artifact",
        )
    return registry
