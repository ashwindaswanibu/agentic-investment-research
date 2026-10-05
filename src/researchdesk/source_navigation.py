"""Bounded navigation of immutable evidence; no retrieval, interpretation or absence claims."""

from __future__ import annotations

import json
from itertools import islice

from pydantic import BaseModel, ConfigDict, Field

from researchdesk.agents.registry import ToolError
from researchdesk.research.models import SourceReference
from researchdesk.research.quality import _pointer, _scalar_excerpt

MAX_SOURCE_PATH_CHARS = 1000  # The existing SourceReference citation contract.
PREVIEW_CHARS = 120


class InspectSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    artifact_id: str = Field(min_length=1, max_length=200, strict=True)
    source_path: str = Field(default="", max_length=MAX_SOURCE_PATH_CHARS, strict=True)
    offset: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    limit: int = Field(default=20, ge=1, le=40, strict=True)
    text_offset: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    text_limit: int = Field(default=2000, ge=1, le=4000, strict=True)


def _fits(result: dict) -> bool:
    # Import locally: domain registers this tool. Count the actual registry envelope
    # with default JSON escaping, including astral Unicode and control characters.
    from researchdesk.domain import MAX_TOOL_RESULT_CHARS

    return len(json.dumps({"ok": True, "data": result}, allow_nan=False)) <= MAX_TOOL_RESULT_CHARS


def _limit_error() -> ToolError:
    return ToolError(
        "source_navigation_limit",
        "The exact source path or required citation cannot fit this tool's bounded response. "
        "Use read_artifact pagination; no source value or absence was inferred.",
    )


def _node_type(value) -> str:
    if value is None:
        return "null"
    for cls, label in (
        (bool, "boolean"),
        (str, "string"),
        (int, "integer"),
        (float, "number"),
        (dict, "object"),
        (list, "array"),
    ):
        if type(value) is cls:
            return label
    raise ToolError("source_content_invalid", "The selected source value is not a JSON value.")


def _citation(artifact: dict, path: str, excerpt: str) -> dict | None:
    if not excerpt.strip():
        return None
    reference = SourceReference(
        artifact_id=artifact["id"],
        artifact_sha256=artifact["sha256"],
        source_path=path,
        excerpt=excerpt,
    ).model_dump(mode="json")
    # Do not silently issue a different pointer if a future schema normalizes keys.
    if reference["source_path"] != path:
        raise ToolError("source_reference_invalid", "The citation cannot preserve this exact path.")
    return reference


def _child(path: str, key: str, value) -> dict:
    child_path = path + "/" + key.replace("~", "~0").replace("/", "~1")
    if len(child_path) > MAX_SOURCE_PATH_CHARS:
        raise _limit_error()
    kind = _node_type(value)
    if kind in ("object", "array"):
        return {
            "source_path": child_path,
            "node_type": kind,
            "child_count": len(value),
            "preview": f"{kind} with {len(value)} children",
            "preview_truncated": False,
        }
    text = value if kind == "string" else _scalar_excerpt(value)
    return {
        "source_path": child_path,
        "node_type": kind,
        "preview": text[:PREVIEW_CHARS],
        "preview_truncated": len(text) > PREVIEW_CHARS,
    }


def _text_page(artifact, args, base, text):
    if args.offset:
        raise ToolError("source_cursor_invalid", "Container offset is not valid for a string.")
    if args.text_offset > len(text):
        raise ToolError("source_cursor_invalid", "Text offset exceeds the selected string length.")

    def make_page(size):
        page = text[args.text_offset : args.text_offset + size]
        end = args.text_offset + len(page)
        return {
            **base,
            "text": page,
            "text_offset": args.text_offset,
            "returned_chars": len(page),
            "total_chars": len(text),
            "next_text_offset": end if end < len(text) else None,
            "citation": _citation(artifact, args.source_path, page),
        }

    low, high = 0, min(args.text_limit, len(text) - args.text_offset)
    if not _fits(make_page(0)):
        raise _limit_error()
    while low < high:
        middle = (low + high + 1) // 2
        if _fits(make_page(middle)):
            low = middle
        else:
            high = middle - 1
    if low == 0 and args.text_offset < len(text):
        raise _limit_error()
    return make_page(low)


def _container_page(args, base, node):
    if args.text_offset:
        raise ToolError("source_cursor_invalid", "Text offset is not valid for a container.")
    if args.offset > len(node):
        raise ToolError("source_cursor_invalid", "Offset exceeds the selected container length.")
    result = {
        **base,
        "offset": args.offset,
        "total_children": len(node),
        "child_order": "lexicographic_key" if isinstance(node, dict) else "array_index",
        "children": [],
        "next_offset": args.offset if args.offset < len(node) else None,
    }
    if not _fits(result):
        raise _limit_error()
    keys = sorted(node) if isinstance(node, dict) else range(len(node))
    for key in islice(keys, args.offset, args.offset + args.limit):
        try:
            child = _child(args.source_path, str(key), node[key])
        except ToolError:
            if result["children"]:
                break
            raise
        end = args.offset + len(result["children"]) + 1
        candidate = {
            **result,
            "children": [*result["children"], child],
            "next_offset": end if end < len(node) else None,
        }
        if not _fits(candidate):
            if not result["children"]:
                raise _limit_error()
            break
        result = candidate
    return result


def inspect_source(research, ctx, args: InspectSourceInput) -> dict:
    """Inspect only evidence reachable through the ordinary research-library gate.

    Cross-case library access follows ResearchTools.artifact; benchmark attempts use
    isolated Stores. A failed lookup is an error, never evidence of clinical absence.
    """
    ctx.check_cancelled()
    artifact = research.artifact(args.artifact_id)
    if artifact["kind"] not in {"evidence", "options_chain", "options_expirations"}:
        from researchdesk.errors import DomainError

        raise DomainError("ARTIFACT_TYPE", "This operation requires retained source evidence.")
    try:
        node = _pointer(artifact["content"], args.source_path)
    except (KeyError, ValueError, IndexError, TypeError):
        raise ToolError(
            "source_path_unavailable",
            "The exact JSON pointer could not be resolved in this retained source. "
            "This lookup failure is not a verified absence claim.",
        ) from None
    kind = _node_type(node)
    base = {
        "artifact_id": artifact["id"],
        "artifact_sha256": artifact["sha256"],
        "source_path": args.source_path,
        "node_type": kind,
    }
    if kind == "string":
        result = _text_page(artifact, args, base, node)
    elif kind in ("object", "array"):
        result = _container_page(args, base, node)
    else:
        if args.offset or args.text_offset:
            raise ToolError(
                "source_cursor_invalid", "Pagination offsets are not valid for scalars."
            )
        result = {
            **base,
            "value": node,
            "citation": _citation(artifact, args.source_path, _scalar_excerpt(node)),
        }
    if not _fits(result):
        raise _limit_error()
    ctx.check_cancelled()
    return result
