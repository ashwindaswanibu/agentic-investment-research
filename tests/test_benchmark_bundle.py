"""Synthetic bundle-boundary tests; no provider calls, trial facts, or model scores."""

from copy import deepcopy
from pathlib import Path
from stat import S_IMODE

import pytest

from researchdesk.research import benchmark_bundle as bundle
from researchdesk.research.benchmark_models import DatasetManifest, public_case_payload
from researchdesk.store import content_hash


def write_json(path, value):
    path.write_bytes(bundle.canonical_bytes(value))


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    # Other development agents edit the package concurrently. Bind a controlled
    # implementation identity here; a separate test checks actual file hashing.
    monkeypatch.setattr(bundle, "implementation_sha256", lambda: "a" * 64)
    blobs = tmp_path / "inputs"
    blobs.mkdir()
    evidence = {"text": "SYNTHETIC evidence: Test A compared with Test B."}
    reference = {
        "schema_version": "clinical-extraction-reference.v1",
        "reference_id": "synthetic-private-reference",
        "coverage": "complete_for_schema",
        "extraction": {"intervention": "SYNTHETIC GOLD LABEL - never candidate-visible"},
        "notes": "Synthetic engineering fixture; not an independently judged medical reference.",
    }
    programmatic_source = {"synthetic_reference_record": "Frozen operator-only structured input"}
    evidence_hash, reference_hash, reference_source_hash = map(
        content_hash, (evidence, reference, programmatic_source)
    )
    for value in (evidence, reference, programmatic_source):
        write_json(blobs / f"{content_hash(value)}.json", value)
    manifest = DatasetManifest.model_validate(
        {
            "suite_id": "synthetic-bundle-tests",
            "version": "1",
            "created_at": "2026-10-05T12:00:00Z",
            "sources": [
                {
                    "source_id": "synthetic-evidence",
                    "version": "1",
                    "artifact_id": "synthetic-source-artifact",
                    "artifact_sha256": evidence_hash,
                    "kind": "evidence",
                    "public_url": "https://example.org/synthetic/evidence",
                    "acquired_at": "2026-10-05T10:00:00Z",
                },
                {
                    "source_id": "synthetic-reference-source",
                    "version": "1",
                    "artifact_id": "synthetic-private-source",
                    "artifact_sha256": reference_source_hash,
                    "kind": "programmatic_reference",
                    "public_url": "https://example.org/synthetic/reference",
                    "acquired_at": "2026-10-05T10:00:00Z",
                },
            ],
            "cases": [
                {
                    "case_id": "synthetic-case",
                    "question": "Extract the fictional treatment.",
                    "issuer_ids": ["synthetic-issuer"],
                    "trial_family_ids": ["synthetic-family"],
                    "split": "development",
                    "source_ids": ["synthetic-evidence"],
                    "reference_id": reference["reference_id"],
                    "reference_sha256": reference_hash,
                    "reference_method": "programmatic",
                    "reference_source_ids": ["synthetic-reference-source"],
                    "scope": "extraction_only",
                }
            ],
        }
    )
    protocol = {
        "protocol_id": "synthetic-protocol",
        "version": "1",
        "created_at": "2026-10-05T13:00:00Z",
        "dataset_manifest_sha256": manifest.sha256,
        "backend": "disabled-synthetic-fixture",
        "model": "no-model",
        "budget": {
            "max_tool_calls": 20,
            "max_model_calls": 40,
            "max_turns_per_task": 10,
            "max_output_tokens": 4000,
            "max_elapsed_seconds": 300,
        },
        "repetitions": 2,
        "common_instructions": "Extract only from fixed synthetic evidence.",
        "fixed_specialist_instructions": {
            "researcher": "Inspect evidence.",
            "coder": "Compute if needed.",
            "reviewer": "Review claims independently.",
        },
        "predeclared_metrics": ["Field precision, recall, F1."],
        "decision_limits": ["Synthetic fixtures cannot establish research quality."],
        "stopping_criteria": ["Retain every declared attempt, including failures."],
    }
    manifest_path = tmp_path / "manifest.json"
    protocol_path = tmp_path / "protocol.json"
    write_json(manifest_path, manifest.model_dump(mode="json"))
    write_json(protocol_path, protocol)
    return {
        "manifest_path": manifest_path,
        "protocol_path": protocol_path,
        "blobs": blobs,
        "output": tmp_path / "frozen",
    }


def test_freeze_materializes_exact_verified_inputs_and_keeps_references_private(inputs):
    extra = inputs["blobs"] / "unreferenced-operator-notes.json"
    write_json(extra, {"private": "should not be copied"})
    receipt = bundle.freeze_bundle(**inputs)
    manifest, protocol, loaded = bundle.load_bundle(inputs["output"])
    assert loaded == receipt
    assert receipt["manifest_sha256"] == manifest.sha256
    assert receipt["protocol_sha256"] == protocol.sha256
    assert receipt["implementation_sha256"] == "a" * 64
    files = {path.name for path in (inputs["output"] / "blobs").iterdir()}
    assert files == {digest + ".json" for digest in receipt["blob_sha256"]}
    assert extra.name not in files
    # The entire operator bundle is private, including reference blobs.
    assert S_IMODE(inputs["output"].stat().st_mode) & 0o077 == 0
    payload = public_case_payload(manifest.cases[0], manifest)
    assert [row["kind"] for row in payload["sources"]] == ["evidence"]
    assert "private" not in str(payload)
    assert "GOLD LABEL" not in str(payload)
    assert manifest.cases[0].reference_sha256 not in str(payload)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"key":1,"key":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b"{",
        b"\xff",
    ],
)
def test_malformed_ambiguous_or_nonfinite_json_is_rejected(tmp_path, raw):
    path = tmp_path / "malformed.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        bundle.read_json(path)


def test_reads_bound_actual_bytes_and_reject_filesystem_aliases(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"ok": true}')
    with pytest.raises(ValueError, match="size limit"):
        bundle.read_json(target, maximum=4)
    symlink = tmp_path / "alias.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        bundle.read_json(symlink)
    with pytest.raises(ValueError, match="regular JSON"):
        bundle.read_json(tmp_path)


def test_manifest_parent_symlink_is_rejected_before_freeze(inputs):
    alias = inputs["output"].parent.parent / (inputs["output"].parent.name + "-alias")
    alias.symlink_to(inputs["manifest_path"].parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        bundle.freeze_bundle(**{**inputs, "manifest_path": alias / "manifest.json"})
    assert not inputs["output"].exists()


def test_symlinked_input_blob_directory_is_rejected_before_freeze(inputs):
    alias = inputs["output"].parent / "blobs-alias"
    alias.symlink_to(inputs["blobs"], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        bundle.freeze_bundle(**{**inputs, "blobs": alias})
    assert not inputs["output"].exists()


def test_published_bundle_cannot_replace_its_blob_directory_with_an_external_alias(inputs):
    bundle.freeze_bundle(**inputs)
    blobs = inputs["output"] / "blobs"
    external = inputs["output"].parent / "external-blobs"
    blobs.rename(external)
    blobs.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        bundle.load_bundle(inputs["output"])


@pytest.mark.parametrize("digest", ["../outside", "a" * 63, "A" * 64, "/" + "a" * 63])
def test_blob_names_cannot_escape_their_directory(tmp_path, digest):
    with pytest.raises(ValueError, match="Invalid content digest"):
        bundle.load_blob(tmp_path, digest)


def test_source_and_reference_tampering_prevents_publication(inputs):
    manifest = bundle.read_json(inputs["manifest_path"])
    for digest in (
        manifest["sources"][0]["artifact_sha256"],
        manifest["cases"][0]["reference_sha256"],
    ):
        path = inputs["blobs"] / f"{digest}.json"
        original = path.read_bytes()
        write_json(path, {"tampered": True})
        with pytest.raises(ValueError, match="integrity"):
            bundle.freeze_bundle(**inputs)
        assert not inputs["output"].exists()
        path.write_bytes(original)


def test_missing_blob_does_not_leave_a_partial_published_bundle(inputs):
    next(inputs["blobs"].iterdir()).unlink()
    with pytest.raises(ValueError, match="regular JSON"):
        bundle.freeze_bundle(**inputs)
    assert not inputs["output"].exists()
    assert not list(inputs["output"].parent.glob(".benchmark-freeze-*"))


def test_materialization_failure_cleans_staging_and_never_publishes(inputs, monkeypatch):
    real_write = Path.write_bytes

    def failing_write(path, data):
        if path.name == "protocol.json" and path.parent.name.startswith(".benchmark-freeze-"):
            raise OSError("Synthetic disk failure")
        return real_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(OSError, match="Synthetic disk failure"):
        bundle.freeze_bundle(**inputs)
    assert not inputs["output"].exists()
    assert not list(inputs["output"].parent.glob(".benchmark-freeze-*"))


def test_materialized_validation_failure_cleans_staging_before_rename(inputs, monkeypatch):
    def failed_validation(_):
        raise ValueError("Synthetic materialized integrity failure")

    monkeypatch.setattr(bundle, "load_bundle", failed_validation)
    with pytest.raises(ValueError, match="materialized integrity"):
        bundle.freeze_bundle(**inputs)
    assert not inputs["output"].exists()
    assert not list(inputs["output"].parent.glob(".benchmark-freeze-*"))


def test_existing_bundle_is_never_overwritten(inputs):
    bundle.freeze_bundle(**inputs)
    before = (inputs["output"] / "binding.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        bundle.freeze_bundle(**inputs)
    assert (inputs["output"] / "binding.json").read_bytes() == before


@pytest.mark.parametrize("target", ["manifest", "protocol", "binding", "blob"])
def test_post_publication_tampering_or_partial_input_is_detected(inputs, target):
    receipt = bundle.freeze_bundle(**inputs)
    if target == "blob":
        path = inputs["output"] / "blobs" / f"{receipt['blob_sha256'][0]}.json"
        write_json(path, {"tampered": True})
    else:
        path = inputs["output"] / f"{target}.json"
        value = bundle.read_json(path)
        if target == "manifest":
            value["cases"][0]["question"] = "Different question after freeze"
        elif target == "protocol":
            value["model"] = "Different model after freeze"
        else:
            value["implementation_sha256"] = "b" * 64
        write_json(path, value)
    with pytest.raises(ValueError):
        bundle.load_bundle(inputs["output"])
    path.unlink()
    with pytest.raises(ValueError):
        bundle.load_bundle(inputs["output"])


def test_changed_implementation_is_rejected_without_reinterpreting_original_bundle(
    inputs, monkeypatch
):
    original = bundle.freeze_bundle(**inputs)
    monkeypatch.setattr(bundle, "implementation_sha256", lambda: "b" * 64)
    with pytest.raises(ValueError, match="implementation changed"):
        bundle.load_bundle(inputs["output"])
    assert bundle.read_json(inputs["output"] / "binding.json") == original


def test_implementation_binding_covers_python_content_and_paths(tmp_path, monkeypatch):
    package = tmp_path / "package"
    research = package / "research"
    research.mkdir(parents=True)
    module = research / "benchmark_bundle.py"
    module.write_text("# synthetic implementation\n")
    evaluator = package / "evaluator.py"
    evaluator.write_text("# synthetic evaluator v1\n")
    monkeypatch.setattr(bundle, "__file__", str(module))
    first = bundle.implementation_sha256()
    evaluator.write_text("# synthetic evaluator v2\n")
    second = bundle.implementation_sha256()
    assert second != first
    evaluator.rename(package / "renamed_evaluator.py")
    assert bundle.implementation_sha256() != second


def test_bundle_size_limit_is_checked_before_publication_and_again_on_load(inputs, monkeypatch):
    bundle.freeze_bundle(**inputs)
    monkeypatch.setattr(bundle, "MAX_BUNDLE_BYTES", 1)
    with pytest.raises(ValueError, match="content limit"):
        bundle.load_bundle(inputs["output"])
    new_output = inputs["output"].parent / "too-large"
    with pytest.raises(ValueError, match="content limit"):
        bundle.freeze_bundle(**{**inputs, "output": new_output})
    assert not new_output.exists()


def test_storage_bound_accounts_for_json_escaped_non_ascii(inputs, monkeypatch):
    content = {"text": "é" * 40}
    digest = content_hash(content)
    write_json(inputs["blobs"] / f"{digest}.json", content)
    assert len(bundle.canonical_bytes(content)) < 150
    monkeypatch.setattr(bundle, "MAX_FILE_BYTES", 150)
    with pytest.raises(ValueError, match="storage limit"):
        bundle.load_blob(inputs["blobs"], digest)


def test_logical_identifiers_are_not_interpreted_as_filesystem_paths(inputs):
    data = bundle.read_json(inputs["manifest_path"])
    data["suite_id"] = "../../synthetic-suite"
    data["cases"][0]["case_id"] = "../../synthetic-case"
    data["sources"][0]["source_id"] = "../../synthetic-source"
    data["cases"][0]["source_ids"] = ["../../synthetic-source"]
    manifest = DatasetManifest.model_validate(data)
    protocol = deepcopy(bundle.read_json(inputs["protocol_path"]))
    protocol["dataset_manifest_sha256"] = manifest.sha256
    write_json(inputs["manifest_path"], manifest.model_dump(mode="json"))
    write_json(inputs["protocol_path"], protocol)
    bundle.freeze_bundle(**inputs)
    assert {path.name for path in inputs["output"].iterdir()} == {
        "manifest.json",
        "protocol.json",
        "binding.json",
        "blobs",
    }
    assert not (inputs["output"].parent / "synthetic-case").exists()
