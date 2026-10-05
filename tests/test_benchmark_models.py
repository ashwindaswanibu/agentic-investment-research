"""Synthetic protocol fixtures only; no medical facts or measured model quality."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from researchdesk.research.benchmark_models import (
    BenchmarkBudget,
    BenchmarkCase,
    BenchmarkProtocol,
    BenchmarkSource,
    DatasetManifest,
    public_case_payload,
    validate_benchmark,
)
from researchdesk.store import content_hash


def source(identifier, **changes):
    return {
        "source_id": identifier,
        "version": "synthetic-v1",
        "kind": "evidence",
        "artifact_id": "artifact-" + identifier,
        "artifact_sha256": content_hash({"synthetic source": identifier}),
        "public_url": f"https://example.org/synthetic/{identifier}",
        "acquired_at": "2026-10-05T12:00:00Z",
        "published_at": "2026-09-01T00:00:00Z",
        "available_at": "2026-09-02T00:00:00Z",
        **changes,
    }


def case(identifier, split, **changes):
    return {
        "case_id": identifier,
        "question": "SYNTHETIC TEST: extract the fictional trial's structured fields.",
        "issuer_ids": ["issuer-" + identifier],
        "trial_family_ids": ["family-" + identifier],
        "split": split,
        "source_ids": [identifier],
        "reference_id": "reference-" + identifier,
        "reference_sha256": content_hash({"synthetic reference": identifier}),
        "reference_method": "programmatic",
        "reference_source_ids": [identifier + "-reference"],
        "scope": "extraction_only",
        "information_cutoff": "2026-09-30T23:59:59Z",
        "historical_as_of": True,
        **changes,
    }


@pytest.fixture
def manifest_data():
    return {
        "suite_id": "synthetic-schema-tests",
        "version": "v1",
        "created_at": "2026-10-05T13:00:00Z",
        "sources": [
            source("dev"),
            source("dev-reference", kind="programmatic_reference"),
            source("final"),
            source("final-reference", kind="programmatic_reference"),
        ],
        "cases": [case("dev", "development"), case("final", "final")],
    }


def protocol_data(manifest):
    return {
        "protocol_id": "synthetic-test-protocol",
        "version": "v1",
        "created_at": "2026-10-05T14:00:00Z",
        "dataset_manifest_sha256": manifest.sha256,
        "backend": "disabled-synthetic-test-provider",
        "model": "no-model-in-schema-tests",
        "budget": {
            "max_tool_calls": 20,
            "max_model_calls": 40,
            "max_turns_per_task": 10,
            "max_output_tokens": 4000,
            "max_elapsed_seconds": 300,
        },
        "repetitions": 2,
        "common_instructions": "SYNTHETIC TEST: produce an attributable extraction.",
        "fixed_specialist_instructions": {
            "researcher": "Inspect only the supplied sources.",
            "coder": "Execute declared calculations when applicable.",
            "reviewer": "Check the retained output independently.",
        },
        "predeclared_metrics": ["Extraction field precision, recall, and F1."],
        "decision_limits": ["No promotion claim from this synthetic fixture."],
        "stopping_criteria": ["Stop after all registered attempts; retain failures."],
    }


def test_round_trip_is_frozen_and_hash_binds_every_source_question_and_protocol(manifest_data):
    manifest = DatasetManifest.model_validate(manifest_data)
    protocol = BenchmarkProtocol.model_validate(protocol_data(manifest))
    assert validate_benchmark(manifest, protocol) == (manifest, protocol)
    assert manifest.sha256 == content_hash(manifest.model_dump(mode="json"))
    assert DatasetManifest.model_validate_json(manifest.model_dump_json()).sha256 == manifest.sha256
    assert (
        BenchmarkProtocol.model_validate_json(protocol.model_dump_json()).sha256 == protocol.sha256
    )
    with pytest.raises(ValidationError, match="frozen"):
        manifest.sources[0].version = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        protocol.fixed_specialist_instructions.researcher = "changed"
    assert isinstance(manifest.cases, tuple)
    changed = deepcopy(manifest_data)
    changed["cases"][0]["question"] += " Additional request."
    with pytest.raises(ValueError, match="does not match"):
        validate_benchmark(DatasetManifest.model_validate(changed), protocol)


@pytest.mark.parametrize("field", ["issuer_ids", "trial_family_ids"])
def test_each_grouping_dimension_independently_blocks_split_leakage(manifest_data, field):
    manifest_data["cases"][1][field] = [manifest_data["cases"][0][field][0].upper()]
    with pytest.raises(ValidationError, match="disjoint"):
        DatasetManifest.model_validate(manifest_data)


@pytest.mark.parametrize("alias", ["source", "digest", "url", "reference"])
def test_aliases_and_private_references_cannot_cross_splits(manifest_data, alias):
    if alias == "source":
        manifest_data["cases"][1]["source_ids"] = ["dev"]
    elif alias == "digest":
        manifest_data["sources"][2]["artifact_sha256"] = manifest_data["sources"][0][
            "artifact_sha256"
        ]
    elif alias == "url":
        manifest_data["sources"][2]["public_url"] = (
            manifest_data["sources"][0]["public_url"] + "#different-anchor"
        )
    else:
        manifest_data["cases"][1]["reference_sha256"] = manifest_data["cases"][0][
            "reference_sha256"
        ]
    with pytest.raises(ValidationError, match="disjoint"):
        DatasetManifest.model_validate(manifest_data)


@pytest.mark.parametrize(
    "record,key", [("sources", "source_id"), ("sources", "artifact_id"), ("cases", "case_id")]
)
def test_record_identities_must_be_unique(manifest_data, record, key):
    manifest_data[record][1][key] = manifest_data[record][0][key]
    with pytest.raises(ValidationError, match="unique"):
        DatasetManifest.model_validate(manifest_data)


@pytest.mark.parametrize("field", ["source_ids", "reference_source_ids"])
def test_unknown_input_or_private_reference_sources_are_rejected(manifest_data, field):
    manifest_data["cases"][0][field] = ["not-in-manifest"]
    with pytest.raises(ValidationError, match="unknown source"):
        DatasetManifest.model_validate(manifest_data)


def test_reference_sources_cannot_be_candidate_inputs_or_mislabeled_provenance(manifest_data):
    manifest_data["cases"][0]["source_ids"] = ["dev-reference"]
    with pytest.raises(ValidationError, match="evidence only"):
        DatasetManifest.model_validate(manifest_data)
    manifest_data["cases"][0]["source_ids"] = ["dev"]
    manifest_data["cases"][0]["reference_source_ids"] = ["dev"]
    with pytest.raises(ValidationError, match="programmatic_reference"):
        DatasetManifest.model_validate(manifest_data)


@pytest.mark.parametrize("alias", ["id", "hash"])
def test_known_reference_labels_cannot_be_disguised_as_evidence(manifest_data, alias):
    if alias == "id":
        manifest_data["sources"][0]["artifact_id"] = manifest_data["cases"][0]["reference_id"]
    else:
        manifest_data["sources"][0]["artifact_sha256"] = manifest_data["cases"][0][
            "reference_sha256"
        ]
    with pytest.raises(ValidationError, match="reference labels"):
        DatasetManifest.model_validate(manifest_data)


@pytest.mark.parametrize("field", ["artifact_id", "artifact_sha256", "public_url", "version"])
def test_sources_require_identity_version_and_public_provenance(field):
    row = source("identity")
    row.pop(field)
    with pytest.raises(ValidationError):
        BenchmarkSource.model_validate(row)


@pytest.mark.parametrize("timestamp", ["acquired_at", "published_at", "available_at"])
def test_source_timestamps_require_timezone_and_normalize_to_utc(timestamp):
    with pytest.raises(ValidationError, match="timezone"):
        BenchmarkSource.model_validate(source("time", **{timestamp: "2026-09-03T00:00:00"}))
    row = BenchmarkSource.model_validate(source("time", **{timestamp: "2026-09-03T02:00:00+02:00"}))
    assert getattr(row, timestamp) == datetime(2026, 9, 3, tzinfo=UTC)


def test_public_urls_reject_credentials_and_sources_cannot_predate_availability():
    with pytest.raises(ValidationError, match="credentials"):
        BenchmarkSource.model_validate(
            source("url", public_url="https://user:secret@example.org/a")
        )
    with pytest.raises(ValidationError, match="available_at"):
        BenchmarkSource.model_validate(source("time", available_at="2026-10-06T00:00:00Z"))


def test_cutoff_needs_exact_version_availability_not_publication_or_acquisition(manifest_data):
    manifest_data["sources"][0]["available_at"] = None
    with pytest.raises(ValidationError, match="requires source available_at"):
        DatasetManifest.model_validate(manifest_data)
    manifest_data["cases"][0]["historical_as_of"] = False
    with pytest.raises(ValidationError, match="requires source available_at"):
        DatasetManifest.model_validate(manifest_data)
    manifest_data["cases"][0]["information_cutoff"] = None
    assert DatasetManifest.model_validate(manifest_data).cases[0].information_cutoff is None


def test_post_cutoff_evidence_rejected_but_later_acquisition_is_not_lookahead(manifest_data):
    assert DatasetManifest.model_validate(manifest_data).sources[0].acquired_at.month == 10
    manifest_data["sources"][0]["available_at"] = "2026-10-01T00:00:00Z"
    with pytest.raises(ValidationError, match="after cutoff"):
        DatasetManifest.model_validate(manifest_data)


def test_historical_case_requires_cutoff_and_manifest_cannot_precede_acquisition(manifest_data):
    manifest_data["cases"][0]["information_cutoff"] = None
    with pytest.raises(ValidationError, match="requires information_cutoff"):
        DatasetManifest.model_validate(manifest_data)
    manifest_data["cases"][0]["historical_as_of"] = False
    manifest_data["created_at"] = "2026-09-30T00:00:00Z"
    with pytest.raises(ValidationError, match="manifest creation"):
        DatasetManifest.model_validate(manifest_data)


def test_reference_method_requires_identity_and_appropriate_evaluation_scope():
    for field in ("reference_id", "reference_sha256", "reference_source_ids"):
        row = case("dev", "development")
        row.pop(field)
        with pytest.raises(ValidationError, match="require"):
            BenchmarkCase.model_validate(row)
    with pytest.raises(ValidationError, match="independently_adjudicated"):
        BenchmarkCase.model_validate(case("dev", "development", scope="dossier_review"))
    adjudicated = BenchmarkCase.model_validate(
        case(
            "dev",
            "development",
            reference_method="independently_adjudicated",
            scope="dossier_review",
        )
    )
    assert adjudicated.scope == "dossier_review"
    unlabelled = case("dev", "development", reference_method="unlabelled")
    with pytest.raises(ValidationError, match="unlabelled"):
        BenchmarkCase.model_validate(unlabelled)
    unlabelled.update(reference_id=None, reference_sha256=None, reference_source_ids=[])
    assert BenchmarkCase.model_validate(unlabelled).reference_id is None


def test_public_task_payload_omits_reference_identity_labels_split_and_private_sources(
    manifest_data,
):
    manifest = DatasetManifest.model_validate(manifest_data)
    payload = public_case_payload(manifest.cases[0], manifest)
    assert set(payload) == {
        "case_id",
        "question",
        "information_cutoff",
        "historical_as_of",
        "sources",
    }
    assert [source["source_id"] for source in payload["sources"]] == ["dev"]
    serialized = str(payload)
    assert "reference-dev" not in serialized
    assert "dev-reference" not in serialized
    assert manifest.cases[0].reference_sha256 not in serialized
    assert "reference_method" not in serialized
    forged = manifest.cases[0].model_copy(update={"question": "Different candidate request"})
    with pytest.raises(ValueError, match="exact case"):
        public_case_payload(forged, manifest)
    with pytest.raises(ValidationError, match="Extra inputs"):
        DatasetManifest.model_validate({**manifest_data, "model_answers": {"dev": "hidden answer"}})


@pytest.mark.parametrize(
    "field,low,high",
    [
        ("max_tool_calls", 1, 200),
        ("max_model_calls", 1, 500),
        ("max_turns_per_task", 1, 100),
        ("max_output_tokens", 1, 32000),
        ("max_elapsed_seconds", 30, 7200),
    ],
)
def test_resource_budgets_have_explicit_strict_bounds(manifest_data, field, low, high):
    values = protocol_data(DatasetManifest.model_validate(manifest_data))["budget"]
    for value in (low, high):
        assert getattr(BenchmarkBudget.model_validate({**values, field: value}), field) == value
    for value in (low - 1, high + 1, True, "20", 1.5):
        with pytest.raises(ValidationError):
            BenchmarkBudget.model_validate({**values, field: value})
    values.pop(field)
    with pytest.raises(ValidationError):
        BenchmarkBudget.model_validate(values)


def test_protocol_freezes_all_three_arms_and_cannot_override_shared_model_or_budget(manifest_data):
    manifest = DatasetManifest.model_validate(manifest_data)
    values = protocol_data(manifest)
    assert len(BenchmarkProtocol.model_validate(values).arms) == 3
    assert (
        BenchmarkProtocol.model_validate(values).comparison
        == "frozen-clinical-profile-adaptation.v1"
    )
    with pytest.raises(ValidationError, match="comparison"):
        BenchmarkProtocol.model_validate({**values, "comparison": "unbounded-autonomous-research"})
    for arms in (["generalist"], ["generalist", "generalist", "adaptive_specialists"]):
        with pytest.raises(ValidationError, match="comparison arm"):
            BenchmarkProtocol.model_validate({**values, "arms": arms})
    with pytest.raises(ValidationError, match="Extra inputs"):
        BenchmarkProtocol.model_validate({**values, "arm_models": {"generalist": "other-model"}})
    values["fixed_specialist_instructions"].pop("reviewer")
    with pytest.raises(ValidationError, match="reviewer"):
        BenchmarkProtocol.model_validate(values)


def test_protocol_cannot_claim_another_dataset_or_precede_its_freeze(manifest_data):
    manifest = DatasetManifest.model_validate(manifest_data)
    values = protocol_data(manifest)
    with pytest.raises(ValueError, match="does not match"):
        validate_benchmark(manifest, {**values, "dataset_manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="precede"):
        validate_benchmark(manifest, {**values, "created_at": "2026-10-05T12:00:00Z"})
    unsafe_copy = manifest.model_copy(update={"cases": ()})
    with pytest.raises(ValidationError):
        validate_benchmark(unsafe_copy, values)
