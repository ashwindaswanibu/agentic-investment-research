"""Builder checks using labelled synthetic sources, plus optional retained-source integration.

Synthetic fixtures establish software behavior only. They are not clinical data,
reference labels for real sources, or evidence of model research quality.
"""

import importlib.util
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from researchdesk.research.benchmark_bundle import canonical_bytes, load_blob, read_json
from researchdesk.research.benchmark_models import DatasetManifest
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.research.scoped_quality import validate_mechanical_reference
from researchdesk.store import content_hash

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime(2026, 10, 5, 16, tzinfo=UTC)


@pytest.fixture
def builder():
    path = ROOT / "examples/build_mechanical_reference_package.py"
    spec = importlib.util.spec_from_file_location("mechanical_reference_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_record(trial):
    endpoints = [
        {"measure": "Synthetic endpoint alpha", "timeFrame": "Synthetic timeframe 1"},
        {"measure": "Synthetic endpoint beta", "timeFrame": "Synthetic timeframe 2"},
    ]
    record = {
        "protocolSection": {
            "identificationModule": {"nctId": trial},
            "designModule": {"enrollmentInfo": {"count": 71, "type": "ACTUAL"}},
            "outcomesModule": {"primaryOutcomes": endpoints[: 2 if trial == "NCT05643742" else 1]},
        },
        "hasResults": trial == "NCT03525444",
    }
    if trial == "NCT03525444":
        outcomes = [{} for _ in range(13)]
        for index, group_ids, values in (
            (0, ["fixture-B", "fixture-A"], ["13", "17"]),
            (9, ["fixture-A", "fixture-B"], ["5", "7"]),
            (12, ["fixture-A"], ["29"]),
        ):
            outcomes[index] = {
                "title": f"Synthetic posted endpoint {index}",
                "timeFrame": f"Synthetic posted timeframe {index}",
                "type": "PRIMARY" if index == 0 else "SECONDARY",
                "groups": [
                    {"id": group_id, "title": f"Synthetic arm {index}-{group_id}"}
                    for group_id in sorted(group_ids)
                ],
                "denoms": [
                    {
                        "units": "Synthetic participants",
                        "counts": [
                            {"groupId": group_id, "value": value}
                            for group_id, value in zip(group_ids, values, strict=True)
                        ],
                    }
                ],
            }
        record["resultsSection"] = {"outcomeMeasuresModule": {"outcomeMeasures": outcomes}}
    return {"fixture_label": "SYNTHETIC SOFTWARE TEST ONLY", "record": record}


@pytest.fixture
def synthetic_package(builder, tmp_path):
    """Same structural IDs as the scoped plan; all record values are explicit fixtures."""

    def create(mutate=None):
        package = tmp_path / "synthetic-input"
        package.mkdir()
        (package / "blobs").mkdir()
        contents, sources = {}, []
        trial_by_source = {source: trial for _, trial, source, _ in builder.CASE_PLANS}
        for source_id in sorted(builder.SOURCE_IDS):
            content = (
                _synthetic_record(trial_by_source[source_id])
                if source_id in trial_by_source
                else {
                    "fixture_label": "SYNTHETIC SOFTWARE TEST ONLY",
                    "text": f"<fixture>{source_id}</fixture>",
                }
            )
            if mutate:
                mutate(source_id, content)
            contents[source_id] = content
            digest = content_hash(content)
            (package / "blobs" / f"{digest}.json").write_bytes(canonical_bytes(content))
            sources.append(
                {
                    "source_id": source_id,
                    "version": "synthetic-fixture-v1",
                    "kind": "evidence",
                    "artifact_id": "sha256:" + digest,
                    "artifact_sha256": digest,
                    "public_url": "https://example.org/synthetic/" + source_id,
                    "acquired_at": "2026-10-05T14:00:00Z",
                }
            )
        extras = {
            "NCT03525444": ["pubmed-31697873-efetch-20261005"],
            "NCT05643742": [],
            "NCT00045968": ["pubmed-29843811-efetch-20261005", "pubmed-36394838-efetch-20261005"],
        }
        manifest = DatasetManifest.model_validate(
            {
                "suite_id": "synthetic-software-checks-only",
                "version": "synthetic-v1",
                "created_at": "2026-10-05T14:10:00Z",
                "sources": sources,
                "cases": [
                    {
                        "case_id": case_id,
                        "question": "Synthetic software behavior check; no clinical labels.",
                        "issuer_ids": [case_id + ".fixture-issuer"],
                        "trial_family_ids": [case_id + ".fixture-family"],
                        "split": "development",
                        "source_ids": [source, *extras[trial]],
                        "reference_method": "unlabelled",
                        "scope": "extraction_only",
                    }
                    for case_id, trial, source, _ in builder.CASE_PLANS
                ],
            }
        )
        (package / "dataset-manifest.json").write_bytes(
            canonical_bytes(manifest.model_dump(mode="json"))
        )
        return package, manifest, contents

    return create


def _assert_package(output, index):
    assert read_json(output / "package-index.json") == index
    binding = {key: value for key, value in index.items() if key != "sha256"}
    assert content_hash(binding) == index["sha256"]
    assert index["model_calls"] == 0 and index["quality_score"] is None
    assert index["authoring"]["prior_source_familiarity"] is True
    assert index["authoring"]["blind_reference_authoring"] is False
    assert index["authoring"]["review_status"] == "unreviewed"
    assert sum(case["observations"] for case in index["cases"]) == 20
    assert sum(case["fields"] for case in index["cases"]) == 38
    assert len(index["blob_sha256"]) == 15
    for digest in index["blob_sha256"]:
        load_blob(output / "blobs", digest)
    for case in index["cases"]:
        scope_json = read_json(output / case["scope_file"])
        scope = MechanicalScope.model_validate(scope_json)
        reference = MechanicalReference.model_validate(read_json(output / case["reference_file"]))
        assert scope.sha256 == case["scope_sha256"] == reference.scope_sha256
        assert reference.sha256 == case["reference_sha256"]
        assert reference.reviewers == ()
        public_text = json.dumps(scope_json)
        for forbidden in (
            "expected_value",
            "expected_state",
            "rationale",
            "reviewers",
            "source_absent",
        ):
            assert forbidden not in public_text
        for field in scope.fields:
            assert field.normalization in {"identity", "canonical_digit_string", "enum_lookup"}
            if field.normalization == "enum_lookup":
                assert field.enum_map is not None
                assert len(field.enum_map) == 2
                assert "enum_map" in field.model_dump(mode="json")
        artifacts = {
            source.source_id: {
                "id": "sha256:" + source.artifact_sha256,
                "kind": "evidence",
                "sha256": source.artifact_sha256,
                "content": load_blob(output / "blobs", source.artifact_sha256),
            }
            for source in scope.sources
        }
        validate_mechanical_reference(scope, reference, artifacts)
        projection = case["projection_source"]
        assert "public_url" not in projection and "upstream_public_url" in projection
        assert projection["kind"] == "programmatic_reference"
        assert case["reference_source_ids"] == [projection["source_id"]]
        ledger = load_blob(output / "blobs", projection["artifact_sha256"])
        assert ledger["reference_sha256"] == reference.sha256
        assert ledger["public_source_bindings"] == scope_json["sources"]
        assert [item["reference"] for item in ledger["field_ledger"]] == [
            field.model_dump(mode="json") for field in reference.fields
        ]
        observations = {item.observation_id: item for item in scope.observations}
        for rule in reference.fields:
            target = next(field for field in scope.fields if field.field_id == rule.field_id)
            requested_path = (
                rule.source_path
                if rule.expected_state == "present"
                else rule.source_path + "/" + rule.missing_key.replace("~", "~0").replace("/", "~1")
            )
            assert target.source_path == requested_path
            observation = observations[target.observation_id]
            if observation.group and target.field_name == "count":
                assert rule.source_group_path == rule.source_path.rsplit("/", 1)[0] + "/groupId"
                assert observation.endpoint_observation_id is not None
                endpoint = observations[observation.endpoint_observation_id]
                assert endpoint.kind == "endpoint" and endpoint.context_id == observation.context_id
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for path in output.rglob("*.json"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_synthetic_projection_is_typed_bound_private_and_separate(
    builder, synthetic_package, tmp_path
):
    package, manifest, contents = synthetic_package()
    original_files = {
        str(path.relative_to(package)): path.read_bytes() for path in package.rglob("*.json")
    }
    output = tmp_path / "references"
    index = builder.build_package(
        package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
    )
    _assert_package(output, index)
    assert original_files == {
        str(path.relative_to(package)): path.read_bytes() for path in package.rglob("*.json")
    }
    vertex = index["cases"][0]
    reference = MechanicalReference.model_validate(read_json(output / vertex["reference_file"]))
    actual = [
        rule.expected_value
        for rule in reference.fields
        if getattr(rule, "normalization", None) == "canonical_digit_string"
    ]
    assert actual == [13, 17, 5, 7, 29]
    assert set(contents) == builder.SOURCE_IDS


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("protocolSection", "designModule", "enrollmentInfo", "count"), True, "raw type"),
        (("protocolSection", "designModule", "enrollmentInfo", "count"), "71", "raw type"),
        (("protocolSection", "designModule", "enrollmentInfo", "type"), "UNDECLARED", "enum token"),
        (("hasResults",), 0, "raw type"),
        (("hasResults",), None, "raw type"),
    ],
)
def test_wrong_raw_types_or_enum_fail_before_output(
    builder, synthetic_package, tmp_path, path, value, match
):
    def mutate(source_id, content):
        if source_id != "ctg-NCT05643742-current-20261005":
            return
        parent = content["record"]
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value

    package, manifest, _ = synthetic_package(mutate)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match=match):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


def test_key_with_explicit_null_is_not_projected_as_absent(builder, synthetic_package, tmp_path):
    def mutate(source_id, content):
        if source_id == "ctg-NCT00045968-current-20261005":
            content["record"]["resultsSection"] = None

    package, manifest, _ = synthetic_package(mutate)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="Missing-key projection"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


@pytest.mark.parametrize("invalid", ["1e2", "-1", " 12", "１２", "01"])
def test_grouped_count_accepts_only_declared_ascii_digit_strings(
    builder, synthetic_package, tmp_path, invalid
):
    def mutate(source_id, content):
        if source_id == "ctg-NCT03525444-current-20261005":
            outcome = content["record"]["resultsSection"]["outcomeMeasuresModule"][
                "outcomeMeasures"
            ][0]
            outcome["denoms"][0]["counts"][0]["value"] = invalid

    package, manifest, _ = synthetic_package(mutate)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="ASCII digit-string"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


def test_ambiguous_group_identity_is_rejected_before_output(builder, synthetic_package, tmp_path):
    def mutate(source_id, content):
        if source_id == "ctg-NCT03525444-current-20261005":
            outcome = content["record"]["resultsSection"]["outcomeMeasuresModule"][
                "outcomeMeasures"
            ][0]
            outcome["groups"][1]["id"] = outcome["groups"][0]["id"]

    package, manifest, _ = synthetic_package(mutate)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="Ambiguous repeated group ID"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


def test_mismatched_blob_hash_fails_before_output(builder, synthetic_package, tmp_path):
    package, manifest, _ = synthetic_package()
    source = manifest.sources[0]
    (package / "blobs" / f"{source.artifact_sha256}.json").write_text('{"tampered":true}')
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="integrity"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


def test_wrong_manifest_pin_and_overwrite_are_rejected(builder, synthetic_package, tmp_path):
    package, manifest, _ = synthetic_package()
    output = tmp_path / "references"
    with pytest.raises(ValueError, match="pinned acquisition"):
        builder.build_package(package, output, created_at=STAMP)
    assert not output.exists()
    output.mkdir()
    (output / "marker").write_text("keep")
    with pytest.raises(FileExistsError):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert (output / "marker").read_text() == "keep"


def test_interrupted_materialization_never_publishes_partial_package(
    builder, synthetic_package, tmp_path, monkeypatch
):
    package, manifest, _ = synthetic_package()
    original_write = builder._write_private
    writes = 0

    def fail_after_first_file(path, value):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("Synthetic filesystem interruption")
        return original_write(path, value)

    monkeypatch.setattr(builder, "_write_private", fail_after_first_file)
    output = tmp_path / "must-not-exist"
    with pytest.raises(OSError, match="Synthetic filesystem"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".mechanical-reference-*"))


def test_output_cannot_write_inside_retained_input(builder, synthetic_package):
    package, manifest, _ = synthetic_package()
    output = package / "new-references"
    with pytest.raises(ValueError, match="outside the retained source package"):
        builder.build_package(
            package, output, expected_manifest_sha256=manifest.sha256, created_at=STAMP
        )
    assert not output.exists()


@pytest.mark.integration
def test_retained_real_sources_build_only_mechanical_unreviewed_references(builder, tmp_path):
    if not builder.DEFAULT_PACKAGE.is_dir():
        pytest.skip("Requires the local retained six-source clinical development package")
    output = tmp_path / "real-reference-package"
    index = builder.build_package(builder.DEFAULT_PACKAGE, output)
    _assert_package(output, index)
    assert index["source_manifest_sha256"] == builder.PINNED_MANIFEST_SHA256
    for case in index["cases"]:
        reference = MechanicalReference.model_validate(read_json(output / case["reference_file"]))
        assert all(rule.source_id.startswith("ctg-") for rule in reference.fields)
