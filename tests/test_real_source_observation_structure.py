"""Optional real-source integration checks, not gold labels or model quality scores.

Requires the documented local six-source acquisition package. CI without those
public-source snapshots skips explicitly rather than substituting invented data.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from researchdesk.store import Store

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def verification():
    path = ROOT / "examples/clinical_observation_verification.py"
    spec = importlib.util.spec_from_file_location("clinical_observation_verification", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not module.DEFAULT_PACKAGE.is_dir():
        pytest.skip(
            "Real-source verification requires the local frozen clinical development package"
        )
    return module


def test_real_source_dossiers_preserve_structure_through_production_tools(verification, tmp_path):
    output = tmp_path / "isolated-verification"
    report = verification.run_verification(verification.DEFAULT_PACKAGE, output)
    assert report["status"] == "passed"
    assert report["sources_imported"] == 6 and report["model_calls"] == 0
    assert report["quality_score"] is None and not report["reference_labels_created"]
    assert "operator_authored" in report["mode"]
    assert report["dataset_manifest_sha256"] == verification.EXPECTED_MANIFEST_SHA256
    assert len(json.dumps(report)) < 12_000
    store = Store(report["database_url"])
    try:
        sources = store.list_artifacts(kind="evidence")
        assert len(sources) == 6
        assert not store.list_artifacts(kind="evaluation_reference")
        assert not store.list_artifacts(kind="evaluation_report")
        saved = {}
        for item in report["dossiers"]:
            artifact = store.get_artifact(item["artifact_id"])
            assert artifact["sha256"] == item["artifact_sha256"]
            assert artifact == json.loads(Path(item["artifact_file"]).read_text())
            assert artifact["content"]["validation"]["valid"]
            assert artifact["metadata"]["execution_eligible"] is False
            dossier = artifact["content"]["dossier"]
            assert dossier["schema_version"] == "clinical-dossier.v2"
            assert dossier["forecast"] is None
            assert verification.LABEL in dossier["uncertainty"]
            calls = store.list_tool_calls(case_id=item["case_id"])
            assert all(call["status"] == "completed" for call in calls)
            assert sum(call["name"] == "submit_clinical_dossier" for call in calls) == 1
            assert sum(call["name"] == "inspect_source" for call in calls) == (
                4 if item["family"] == "vertex" else 0
            )
            saved[item["family"]] = dossier
        verification.verify_preservation(saved)
    finally:
        store.close()
    with pytest.raises(FileExistsError):
        verification.run_verification(verification.DEFAULT_PACKAGE, output)


def test_corrupt_frozen_source_fails_before_creating_an_isolated_store(verification, tmp_path):
    package = tmp_path / "corrupt-package"
    shutil.copytree(verification.DEFAULT_PACKAGE, package)
    manifest = json.loads((package / "dataset-manifest.json").read_text())
    digest = manifest["sources"][0]["artifact_sha256"]
    (package / "blobs" / f"{digest}.json").write_text('{"tampered":true}')
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="integrity"):
        verification.run_verification(package, output)
    assert not output.exists()


def test_same_publication_preserves_assignment_and_analysis_with_exact_source_proof(
    verification, tmp_path
):
    report = verification.run_verification(verification.DEFAULT_PACKAGE, tmp_path / "same-source")
    store = Store(report["database_url"])
    try:
        result = next(item for item in report["dossiers"] if item["family"] == "dcvax")
        saved = store.get_artifact(result["artifact_id"])["content"]["dossier"]
        contexts = {item["context_id"]: item for item in saved["contexts"]}
        observations = {item["observation_id"]: item for item in saved["observations"]}
        assignment = observations["dcvax.later_original_assignment"]
        analysis = observations["dcvax.external_comparison"]
        assignment_context = contexts[assignment["context_id"]]
        analysis_context = contexts[analysis["context_id"]]
        assert assignment_context["context_id"] != analysis_context["context_id"]
        assert assignment_context["analysis_id"] != analysis_context["analysis_id"]
        assert assignment_context["source"] == analysis_context["source"]
        assert assignment["design_scope"] == "trial_assignment"
        assert assignment["allocation"] == {"state": "present", "value": "randomized"}
        assert analysis["design_scope"] == "analysis_comparison"
        assert analysis["allocation"] == {"state": "present", "value": "nonrandomized"}

        source = store.get_artifact(assignment_context["source"]["artifact_id"])
        assert source["metadata"]["source_id"] == "pubmed-36394838-efetch-20261005"
        assert assignment_context["source"]["artifact_sha256"] == source["sha256"]
        assert assignment_context["source"]["source_path"] == "/text"
        # These are retained source excerpts, not independently adjudicated labels.
        assert assignment["source_refs"][0]["excerpt"] == (
            "A total of 331 patients were enrolled in the trial, with 232 randomized "
            "to the DCVax-L group and 99 to the placebo group."
        )
        for observation in (assignment, analysis):
            ref = observation["source_refs"][0]
            assert ref["artifact_id"] == source["id"]
            assert ref["artifact_sha256"] == source["sha256"]
            assert ref["source_path"] == "/text"
            assert ref["excerpt"] in source["content"]["text"]
        assert "externally controlled nonrandomized" in analysis["source_refs"][0]["excerpt"]
        assert any(
            set(item["observation_ids"])
            == {assignment["observation_id"], analysis["observation_id"]}
            and item["relationship"] == "compatible_contexts"
            and item["kind"] == "inference"
            for item in saved["reconciliations"]
        )

        absence = observations["dcvax.results_section_key"]["available"]
        assert absence["state"] == "source_absent"
        proof = absence["proof"]
        assert proof["key"] == "resultsSection"
        assert proof["parent"] == contexts["dcvax.registry"]["source"]
        registry_source = store.get_artifact(proof["parent"]["artifact_id"])
        assert proof["parent"]["artifact_sha256"] == registry_source["sha256"]
        assert registry_source["metadata"]["source_id"] == "ctg-NCT00045968-current-20261005"
        assert proof["parent"]["source_path"] == "/record"
        assert "resultsSection" not in registry_source["content"]["record"]
        assert registry_source["content"]["record"]["hasResults"] is False
        assert observations["dcvax.registry_results"]["available"] == {
            "state": "present",
            "value": False,
        }
        assert saved["forecast"] is None
        assert report["quality_score"] is None and not report["reference_labels_created"]
    finally:
        store.close()


def test_changed_manifest_is_not_silently_reinterpreted_as_the_documented_corpus(
    verification, tmp_path
):
    package = tmp_path / "changed-package"
    shutil.copytree(verification.DEFAULT_PACKAGE, package)
    path = package / "dataset-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["cases"][0]["question"] = "An altered source-selection question"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="pinned acquisition"):
        verification.load_package(package)
