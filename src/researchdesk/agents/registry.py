"""Validated, role-scoped application tools. No model-selected host commands."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from researchdesk.errors import DomainError


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ToolContext:
    store: Any
    case_id: str
    task_id: str
    call_id: str
    worker_id: str
    cancelled: Callable[[], bool]

    @property
    def idempotency_key(self) -> str:
        return f"{self.task_id}:{self.call_id}"

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise ToolError("cancelled", "Task was cancelled or its worker lease was lost.")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    roles: frozenset[str]
    handler: Callable[[ToolContext, BaseModel], Any]
    side_effect: str


@dataclass(frozen=True)
class TaskPolicy:
    """Verified task restrictions; profile prose is never an authorization source."""

    allowed_tools: frozenset[str] | None = None
    instructions: str = ""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._task_policy_resolver: Callable[[Any, dict], TaskPolicy] | None = None

    def set_task_policy_resolver(self, resolver: Callable[[Any, dict], TaskPolicy]) -> None:
        if self._task_policy_resolver is not None:
            raise ValueError("Task policy resolver is already installed")
        self._task_policy_resolver = resolver

    def task_policy(self, store: Any, task: dict) -> TaskPolicy:
        if self._task_policy_resolver:
            return self._task_policy_resolver(store, task)
        if any(
            store.get_artifact(identifier)["kind"] == "specialist_activation"
            for identifier in task.get("artifact_ids", [])
        ):
            raise ToolError(
                "specialist_unavailable", "The registry cannot validate pinned specialist profiles."
            )
        return TaskPolicy()

    def allowed_names(self, role: str) -> frozenset[str]:
        return frozenset(t.name for t in self._tools.values() if role in t.roles)

    def register(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        roles: set[str] | frozenset[str],
        handler: Callable[[ToolContext, Any], Any],
        side_effect: str = "read",
    ) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name):
            raise ValueError("Invalid tool name")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        if not roles or not set(roles) <= {"researcher", "coder", "reviewer", "coordinator"}:
            raise ValueError("Tools require known, explicit roles")
        self._tools[name] = ToolDefinition(
            name, description, input_model, frozenset(roles), handler, side_effect
        )

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def tools_for(self, role: str, *, allowed_tools: frozenset[str] | None = None) -> list[dict]:
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_model.model_json_schema(),
                "strict": False,
            }
            for t in self._tools.values()
            if role in t.roles and (allowed_tools is None or t.name in allowed_tools)
        ]

    def describe(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "roles": sorted(t.roles),
                "side_effect": t.side_effect,
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, arguments: Any, context: ToolContext) -> dict:
        try:
            context.check_cancelled()
            tool = self._tools.get(name)
            if tool is None:
                raise ToolError("unknown_tool", f"Unknown tool: {name}")
            task = context.store.get_task(context.task_id)
            if task["role"] not in tool.roles:
                raise ToolError("forbidden_tool", "This task role cannot use that tool.")
            policy = self.task_policy(context.store, task)
            if policy.allowed_tools is not None and name not in policy.allowed_tools:
                raise ToolError(
                    "specialist_tool_forbidden",
                    "The reviewed specialist profile excludes this tool.",
                )
            if not isinstance(arguments, dict):
                raise ToolError("invalid_arguments", "Tool arguments must be a JSON object.")
            try:
                json.dumps(arguments, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise ToolError(
                    "invalid_arguments", "Arguments must contain finite JSON values."
                ) from exc
            # Reject extra fields even if a tool author omitted extra='forbid'.
            if set(arguments) - set(tool.input_model.model_fields):
                raise ToolError("invalid_arguments", "Unexpected tool argument fields.")
            validated = tool.input_model.model_validate(arguments)
            if tool.side_effect == "artifact":
                recovered = context.store.recover_tool_artifact(
                    context.task_id,
                    context.call_id,
                    name,
                    arguments,
                    worker_id=context.worker_id,
                )
                if recovered is not None:
                    from researchdesk.domain import compact_artifact

                    return {"ok": True, "data": compact_artifact(recovered)}
            result = tool.handler(context, validated)
            # Persistable JSON is part of the boundary, including finite numbers.
            json.dumps(result, allow_nan=False)
            return {"ok": True, "data": result}
        except ToolError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        except DomainError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        except ValidationError as exc:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments",
                    "message": json.dumps(
                        exc.errors(include_input=False, include_url=False), default=str
                    ),
                },
            }
        except Exception:
            # Exceptions can contain request URLs, credentials, or private source text.
            return {
                "ok": False,
                "error": {
                    "code": "tool_failed",
                    "message": "The tool failed. No successful result was recorded.",
                },
            }
