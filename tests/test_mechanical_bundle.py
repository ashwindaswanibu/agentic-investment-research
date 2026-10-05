"""Freeze public guidance without putting private projections into agent inputs."""

import json
from copy import deepcopy

import pytest
from test_benchmark_bundle import inputs as inputs_fixture
from test_scoped_quality import fixture as fixture_data

from researchdesk.research.benchmark_bundle import (
    canonical_bytes,
    freeze_bundle,
    load_bundle,
    read_json,
)
from researchdesk.research.benchmark_models import BenchmarkProtocol, DatasetManifest
from researchdesk.research.benchmark_runner import _prepare
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.store import Store, content_hash

inputs = inputs_fixture
scoped_fixture = fixture_data


@pytest.fixture
def guided_inputs(inputs, scoped_fixture):
    _, scope, reference, sources = deepcopy(scoped_fixture)
    manifest = read_json(inputs["manifest_path"])
    scope["case_id"] = manifest["cases"][0]["case_id"]
    public = MechanicalScope.model_validate(scope)
    reference["scope_sha256"] = public.sha256
    private = MechanicalReference.model_validate(reference)
    evidence = sources["stable-source"]
    manifest["sources"][0].update(
        source_id="stable-source", artifact_id=evidence["id"], artifact_sha256=evidence["sha256"]
    )
    manifest["cases"][0].update(
        source_ids=["stable-source"],
        reference_id=private.reference_id,
        reference_sha256=private.sha256,
    )
    manifest = DatasetManifest.model_validate(manifest)
    protocol = read_json(inputs["protocol_path"])
    protocol.update(
        dataset_manifest_sha256=manifest.sha256,
        public_scopes=[
            {
                "case_id": public.case_id,
                "scope_id": public.scope_id,
                "scope_sha256": public.sha256,
            }
        ],
    )
    inputs["manifest_path"].write_bytes(canonical_bytes(manifest.model_dump(mode="json")))
    inputs["protocol_path"].write_bytes(canonical_bytes(protocol))
    for value in (
        evidence["content"],
        public.model_dump(mode="json"),
        private.model_dump(mode="json"),
    ):
        (inputs["blobs"] / f"{content_hash(value)}.json").write_bytes(canonical_bytes(value))
    return inputs


def test_legacy_protocol_canonical_hash_unchanged_without_scope(inputs):
    raw = read_json(inputs["protocol_path"])
    parsed = BenchmarkProtocol.model_validate(raw)
    assert "public_scopes" not in parsed.model_dump(mode="json")
    # Explicit defaults represent the pre-extension canonical contract.
    expected = dict(
        raw,
        schema_version="research-benchmark-protocol.v1",
        comparison="frozen-clinical-profile-adaptation.v1",
        arms=["generalist", "fixed_specialists", "adaptive_specialists"],
    )
    assert parsed.sha256 == content_hash(expected)
    assert BenchmarkProtocol.model_validate(dict(raw, public_scopes=[])).sha256 == parsed.sha256


def test_scopes_are_frozen_but_private_projection_never_enters_attempt_store(
    guided_inputs, tmp_path
):
    receipt = freeze_bundle(**guided_inputs)
    manifest, protocol, _ = load_bundle(guided_inputs["output"])
    assert protocol.public_scopes[0].scope_sha256 in receipt["blob_sha256"]
    assert "scoped source projection verified" in receipt["reference_validation"]
    store = Store(f"sqlite:///{tmp_path / 'attempt.sqlite'}")
    try:
        case, root = _prepare(
            store,
            guided_inputs["output"],
            manifest,
            protocol,
            manifest.cases[0],
            {"arm": "generalist"},
        )
        artifacts = store.list_artifacts(case["id"])
        public = next(item for item in artifacts if item["kind"] == "note")["content"]
        local_source = next(item for item in artifacts if item["kind"] == "evidence")
        assert public["mechanical_scope_sha256"] == protocol.public_scopes[0].scope_sha256
        assert public["sources"][0]["artifact_id"] == local_source["id"] != "local-artifact"
        assert public["mechanical_scope"]["sources"][0]["source_id"] == "stable-source"
        serialized = json.dumps(artifacts) + json.dumps(root)
        for private in (
            "PRIVATE_NOTES",
            "expected_value",
            "private-reference",
            "synthetic-private-source",
        ):
            assert private not in serialized
        assert {a["kind"] for a in artifacts} == {"note", "evidence"}
    finally:
        store.close()


@pytest.mark.parametrize("change", ["case", "source_version", "private_extra", "expected_value"])
def test_hash_consistent_but_invalid_scope_or_reference_stops_freeze(guided_inputs, change):
    protocol = read_json(guided_inputs["protocol_path"])
    manifest = read_json(guided_inputs["manifest_path"])
    binding = protocol["public_scopes"][0]
    scope = read_json(guided_inputs["blobs"] / f"{binding['scope_sha256']}.json")
    reference = read_json(
        guided_inputs["blobs"] / f"{manifest['cases'][0]['reference_sha256']}.json"
    )
    if change == "case":
        scope["case_id"] = "unrelated-case"
    elif change == "source_version":
        scope["sources"][0]["artifact_sha256"] = "b" * 64
    elif change == "private_extra":
        scope["expected_value"] = "SENTINEL ANSWER"
    else:
        reference["fields"][0]["expected_value"] = 999
    binding["scope_sha256"] = content_hash(scope)
    reference["scope_sha256"] = content_hash(scope)
    manifest["cases"][0]["reference_sha256"] = content_hash(reference)
    manifest = DatasetManifest.model_validate(manifest)
    protocol["dataset_manifest_sha256"] = manifest.sha256
    guided_inputs["manifest_path"].write_bytes(canonical_bytes(manifest.model_dump(mode="json")))
    guided_inputs["protocol_path"].write_bytes(canonical_bytes(protocol))
    for value in (scope, reference):
        (guided_inputs["blobs"] / f"{content_hash(value)}.json").write_bytes(canonical_bytes(value))
    with pytest.raises(ValueError):
        freeze_bundle(**guided_inputs)
    assert not guided_inputs["output"].exists()


def test_protocol_cannot_omit_or_duplicate_a_case_scope(guided_inputs):
    protocol = read_json(guided_inputs["protocol_path"])
    protocol["public_scopes"][0]["case_id"] = "not-the-case"
    guided_inputs["protocol_path"].write_bytes(canonical_bytes(protocol))
    with pytest.raises(ValueError, match="every case"):
        freeze_bundle(**guided_inputs)
    protocol["public_scopes"] *= 2
    with pytest.raises(ValueError, match="unique"):
        BenchmarkProtocol.model_validate(protocol)
