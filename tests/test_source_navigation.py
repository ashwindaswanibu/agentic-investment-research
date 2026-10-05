"""Navigation boundary tests; registry-shaped fixtures are not clinical reference labels."""

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from researchdesk.agents import ToolContext, ToolRegistry
from researchdesk.agents.registry import ToolError
from researchdesk.config import Settings
from researchdesk.db import ArtifactRow
from researchdesk.domain import MAX_TOOL_RESULT_CHARS, ResearchTools
from researchdesk.errors import DomainError
from researchdesk.research.models import SourceReference
from researchdesk.research.quality import _pointer, _scalar_excerpt
from researchdesk.source_navigation import InspectSourceInput, inspect_source
from researchdesk.store import Store


@pytest.fixture
def desk(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'source-navigation.db'}")
    case = store.create_case("Source navigation fixture", "Read-only engineering checks")
    task = store.create_task(case["id"], "researcher", "Inspect retained evidence")
    ctx = ToolContext(store, case["id"], task["id"], "inspect", "test-worker", lambda: False)
    research = ResearchTools(store, Settings(_env_file=None, artifact_dir=tmp_path))
    registry = ToolRegistry()
    registry.register(
        "inspect_source",
        "Inspect a retained source",
        InspectSourceInput,
        {"researcher"},
        lambda context, args: inspect_source(research, context, args),
    )
    yield store, case, ctx, research, registry
    store.close()


def source(desk, content, *, kind="evidence", case_id=None):
    store, case, *_ = desk
    return store.put_artifact(
        case_id or case["id"], None, kind, "Navigation engineering fixture", content
    )


def inspect(desk, artifact, path="", **kwargs):
    _, _, ctx, research, _ = desk
    return inspect_source(
        research, ctx, InspectSourceInput(artifact_id=artifact["id"], source_path=path, **kwargs)
    )


def assert_bounded(result):
    assert len(json.dumps({"ok": True, "data": result}, allow_nan=False)) <= MAX_TOOL_RESULT_CHARS


@pytest.mark.parametrize(
    "value,kind,excerpt",
    [
        (405, "integer", "405"),
        (0, "integer", "0"),
        (1.0, "number", "1.0"),
        (False, "boolean", "false"),
        (True, "boolean", "true"),
        (None, "null", "null"),
    ],
)
def test_exact_scalar_values_and_citations_preserve_types_and_full_hash(desk, value, kind, excerpt):
    artifact = source(desk, {"record": {"value": value}})
    result = inspect(desk, artifact, "/record/value")
    assert result["node_type"] == kind
    assert type(result["value"]) is type(value) and result["value"] == value
    assert result["artifact_sha256"] == artifact["sha256"]
    ref = SourceReference.model_validate(result["citation"])
    assert ref.artifact_id == artifact["id"] and ref.artifact_sha256 == artifact["sha256"]
    assert ref.source_path == "/record/value" and ref.excerpt == excerpt
    assert _scalar_excerpt(_pointer(artifact["content"], ref.source_path)) == ref.excerpt
    assert_bounded(result)


def test_root_null_is_valid_but_missing_pointer_is_an_explicit_error(desk):
    artifact = source(desk, None)
    assert inspect(desk, artifact)["citation"]["excerpt"] == "null"
    with pytest.raises(ToolError, match="not a verified absence") as error:
        inspect(desk, artifact, "/absent")
    assert error.value.code == "source_path_unavailable"


def test_registry_shaped_source_can_be_navigated_without_loading_subtrees(desk):
    # Compact source-shape fixture from public NCT03525444, acquired 2026-10-05.
    # The new fixture hash identifies this fragment, not the original raw record.
    content = {
        "record": {
            "protocolSection": {
                "designModule": {"enrollmentInfo": {"count": 405, "type": "ACTUAL"}}
            },
            "resultsSection": {
                "outcomeMeasuresModule": {
                    "outcomeMeasures": [
                        {
                            "groups": [{"id": "OG000", "title": "Placebo"}],
                            "denoms": [
                                {
                                    "units": "Participants",
                                    "counts": [{"groupId": "OG000", "value": "203"}],
                                }
                            ],
                        },
                        {"groups": [{"id": "OG000", "title": "VX-445/TEZ/IVA TC"}]},
                    ]
                }
            },
            "hasResults": True,
        }
    }
    artifact = source(desk, content)
    root = inspect(desk, artifact)
    assert root["children"] == [
        {
            "source_path": "/record",
            "node_type": "object",
            "child_count": 3,
            "preview": "object with 3 children",
            "preview_truncated": False,
        }
    ]
    assert "405" not in json.dumps(root) and "citation" not in root
    numeric = inspect(desk, artifact, "/record/protocolSection/designModule/enrollmentInfo/count")
    assert numeric["value"] == 405
    stem = "/record/resultsSection/outcomeMeasuresModule/outcomeMeasures"
    raw_count = inspect(desk, artifact, stem + "/0/denoms/0/counts/0/value")
    assert raw_count["node_type"] == "string" and raw_count["text"] == "203"
    assert "value" not in raw_count
    assert inspect(desk, artifact, stem + "/0/groups/0/title")["text"] == "Placebo"
    assert inspect(desk, artifact, stem + "/1/groups/0/title")["text"] == "VX-445/TEZ/IVA TC"
    assert len(desk[0].list_artifacts()) == 1  # Inspection cannot create or modify artifacts.


def test_escaped_keys_empty_key_and_whitespace_are_exact_pointer_segments(desk):
    artifact = source(desk, {"a/b": {"~key": [None, "selected"]}, "": 0, "key ": False})
    root = inspect(desk, artifact)
    assert {child["source_path"] for child in root["children"]} == {"/", "/a~1b", "/key "}
    assert inspect(desk, artifact, "/a~1b/~0key/1")["citation"]["excerpt"] == "selected"
    assert inspect(desk, artifact, "/")["value"] == 0
    result = inspect(desk, artifact, "/key ")
    assert result["citation"]["source_path"] == "/key "


@pytest.mark.parametrize(
    "path", ["record", "/~", "/~2", "/list/01", "/list/-1", "/list/-", "/list/3", "/missing"]
)
def test_malformed_and_unavailable_pointers_never_return_absence_observations(desk, path):
    artifact = source(desk, {"list": [0, False, None]})
    result = desk[4].execute(
        "inspect_source", {"artifact_id": artifact["id"], "source_path": path}, desk[2]
    )
    assert result["ok"] is False and "data" not in result
    assert result["error"]["code"] == "source_path_unavailable"


@pytest.mark.parametrize(
    "args",
    [
        {"offset": -1},
        {"limit": 0},
        {"limit": 41},
        {"offset": True},
        {"text_offset": -1},
        {"text_limit": 0},
        {"text_limit": 4001},
        {"text_limit": "10"},
        {"source_path": "/" * 1001},
        {"source_path": False},
        {"unexpected": 1},
    ],
)
def test_admission_bounds_reject_invalid_or_coerced_arguments(args):
    with pytest.raises(ValidationError):
        InspectSourceInput(artifact_id="source", **args)


def test_containers_have_deterministic_order_progress_and_no_subtree_dump(desk):
    artifact = source(
        desk, {str(i).zfill(3): {"secret_subtree": ["not expanded"]} for i in range(95, -1, -1)}
    )
    offset, paths = 0, []
    while True:
        page = inspect(desk, artifact, offset=offset, limit=13)
        assert page["child_order"] == "lexicographic_key" and page["total_children"] == 96
        assert 1 <= len(page["children"]) <= 13 and "not expanded" not in json.dumps(page)
        paths.extend(child["source_path"] for child in page["children"])
        assert_bounded(page)
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert paths == [f"/{i:03}" for i in range(96)]
    assert inspect(desk, artifact, offset=96)["children"] == []
    with pytest.raises(ToolError) as error:
        inspect(desk, artifact, offset=97)
    assert error.value.code == "source_cursor_invalid"


def test_array_indexes_keep_order_and_preview_raw_types(desk):
    artifact = source(desk, ["203", 203, False, None, ["hidden"]])
    page = inspect(desk, artifact, offset=1, limit=3)
    assert [(x["source_path"], x["node_type"]) for x in page["children"]] == [
        ("/1", "integer"),
        ("/2", "boolean"),
        ("/3", "null"),
    ]
    assert page["next_offset"] == 4
    assert inspect(desk, artifact, offset=4)["children"][0]["child_count"] == 1


@pytest.mark.parametrize("text", ["", " \n\t ", '\U0001f9ec\x00"\\\n' * 3000])
def test_text_pages_fit_escaped_envelope_make_progress_and_reassemble_exactly(desk, text):
    artifact = source(desk, {"text": text})
    offset, parts = 0, []
    while True:
        page = inspect(desk, artifact, "/text", text_offset=offset, text_limit=4000)
        assert page["total_chars"] == len(text)
        assert page["returned_chars"] <= 4000
        assert_bounded(page)
        parts.append(page["text"])
        if page["citation"] is not None:
            ref = SourceReference.model_validate(page["citation"])
            assert ref.excerpt in text and ref.source_path == "/text"
        else:
            assert not page["text"].strip()
        if page["next_text_offset"] is None:
            break
        assert page["next_text_offset"] > offset
        offset = page["next_text_offset"]
    assert "".join(parts) == text
    assert inspect(desk, artifact, "/text", text_offset=len(text))["citation"] is None
    with pytest.raises(ToolError) as error:
        inspect(desk, artifact, "/text", text_offset=len(text) + 1)
    assert error.value.code == "source_cursor_invalid"


def test_long_escaped_child_paths_reduce_page_size_without_truncating_identities(desk):
    key = "\U0001f9ec" * 650
    artifact = source(desk, {key + str(i): "\x00" * 500 for i in range(6)})
    offset, seen = 0, []
    while True:
        page = inspect(desk, artifact, offset=offset, limit=40)
        assert_bounded(page)
        assert len(page["children"]) < 6
        for child in page["children"]:
            seen.append(child["source_path"])
            assert child["preview_truncated"]
            assert _pointer(artifact["content"], child["source_path"]) == "\x00" * 500
            assert_bounded(inspect(desk, artifact, child["source_path"]))
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert len(seen) == len(set(seen)) == 6


def test_unrepresentable_paths_fail_explicitly_instead_of_truncating_or_stalling(desk):
    artifact = source(desk, {"x" * 1100: 1})
    with pytest.raises(ToolError) as error:
        inspect(desk, artifact)
    assert error.value.code == "source_navigation_limit"
    # Within the pointer character limit but too large when duplicated in the
    # scalar metadata and exact citation under JSON's default Unicode escaping.
    key = "\U0001f9ec" * 999
    artifact = source(desk, {key: 1})
    assert_bounded(inspect(desk, artifact))
    with pytest.raises(ToolError) as error:
        inspect(desk, artifact, "/" + key)
    assert error.value.code == "source_navigation_limit"


@pytest.mark.parametrize(
    "value,args",
    [
        (1, {"offset": 1}),
        (False, {"text_offset": 1}),
        ([], {"text_offset": 1}),
        ("text", {"offset": 1}),
    ],
)
def test_cursor_for_wrong_node_type_is_not_silently_ignored(desk, value, args):
    artifact = source(desk, value)
    with pytest.raises(ToolError) as error:
        inspect(desk, artifact, **args)
    assert error.value.code == "source_cursor_invalid"


@pytest.mark.parametrize(
    "kind,code",
    [
        ("note", "ARTIFACT_TYPE"),
        ("evaluation_reference", "PROTECTED_EVALUATION"),
        ("evaluation_report", "PROTECTED_EVALUATION"),
    ],
)
def test_source_navigation_preserves_protected_and_evidence_kind_gates(desk, kind, code):
    artifact = source(desk, {"private": "cannot read"}, kind=kind)
    with pytest.raises(DomainError) as error:
        inspect(desk, artifact)
    assert error.value.code == code


def test_corrupted_content_is_rejected_before_any_preview(desk):
    artifact = source(desk, {"value": 405})
    with desk[0].transaction() as session:
        session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == artifact["id"])
            .values(content={"value": 999})
        )
    result = desk[4].execute("inspect_source", {"artifact_id": artifact["id"]}, desk[2])
    assert result["ok"] is False and result["error"]["code"] == "ARTIFACT_CORRUPT"
    assert "999" not in json.dumps(result)


def test_existing_shared_library_access_is_preserved_without_global_caching(desk, tmp_path):
    other = desk[0].create_case("Library case", "Shared research source")
    artifact = source(desk, {"value": 405}, case_id=other["id"])
    assert inspect(desk, artifact, "/value")["value"] == 405
    isolated = Store(f"sqlite:///{tmp_path / 'isolated-attempt.db'}")
    try:
        research = ResearchTools(isolated, Settings(_env_file=None, artifact_dir=tmp_path))
        with pytest.raises(DomainError) as error:
            inspect_source(research, desk[2], InspectSourceInput(artifact_id=artifact["id"]))
        assert error.value.code == "NOT_FOUND"
    finally:
        isolated.close()


def test_cancelled_inspection_stops_before_source_access(desk, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Cancelled tool must not read an artifact")

    monkeypatch.setattr(desk[3], "artifact", fail)
    with pytest.raises(ToolError) as error:
        inspect_source(
            desk[3], replace(desk[2], cancelled=lambda: True), InspectSourceInput(artifact_id="x")
        )
    assert error.value.code == "cancelled"
