"""All examples below are synthetic engineering fixtures, not medical evidence."""

from copy import deepcopy

import pytest

from researchdesk.research import (
    ClinicalDossier,
    ClinicalExtraction,
    ExtractionReference,
    score_extraction,
    validate_dossier,
)
from researchdesk.store import content_hash


@pytest.fixture
def evidence():
    content = {
        "title": "SYNTHETIC TEST EVIDENCE — no real trial or medical claim",
        "record": {
            "description": "The fictional trial randomized 40 adults to Test A or Test B.\n"
            "The prespecified primary endpoint was fictional score change at week 12.",
            "a/b": {"tilde~key": "Synthetic safety data were not reported."},
        },
    }
    artifact = {
        "id": "synthetic-source",
        "kind": "evidence",
        "content": content,
        "sha256": content_hash(content),
    }
    return {artifact["id"]: artifact}


@pytest.fixture
def dossier(evidence):
    source = evidence["synthetic-source"]
    reference = {
        "artifact_id": source["id"],
        "artifact_sha256": source["sha256"],
        "excerpt": "The fictional trial randomized 40 adults to Test A or Test B.",
        "source_path": "/record/description",
    }
    return {
        "schema_version": "clinical-dossier.v1",
        "intervention": "Test A",
        "indication": "Synthetic condition",
        "population": "40 fictional adults",
        "trials": [
            {
                "trial_id": "SYNTHETIC-TRIAL-001",
                "design": {
                    "study_type": "interventional",
                    "allocation": "randomized",
                    "masking": "unknown",
                    "phase": "unknown",
                },
                "arms": [
                    {
                        "arm_id": "a",
                        "label": "Test arm",
                        "intervention": "Test A",
                        "role": "treatment",
                        "planned_n": 20,
                        "source_claim_ids": ["c1"],
                    },
                    {
                        "arm_id": "b",
                        "label": "Comparator",
                        "intervention": "Test B",
                        "role": "comparator",
                        "planned_n": 20,
                        "source_claim_ids": ["c1"],
                    },
                ],
                "endpoints": [
                    {
                        "endpoint_id": "primary",
                        "name": "Fictional score change",
                        "kind": "primary",
                        "timeframe": "Week 12",
                        "prespecified": "yes",
                        "source_claim_ids": ["c1"],
                    }
                ],
                "source_claim_ids": ["c1", "c2"],
            }
        ],
        "claims": [
            {
                "id": "c1",
                "kind": "fact",
                "statement": "The source describes randomization.",
                "trial_ids": ["SYNTHETIC-TRIAL-001"],
                "source_refs": [reference],
            },
            {
                "id": "c2",
                "kind": "inference",
                "statement": "Randomization alone does not establish an unbiased effect estimate.",
                "trial_ids": ["SYNTHETIC-TRIAL-001"],
                "source_refs": [deepcopy(reference)],
                "inference_basis": "Missing masking and outcome data leave unresolved limitations.",
            },
        ],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "No contrary finding was present in the synthetic fixture; "
        "this is not a comprehensive literature search.",
        "missing_inputs": [
            {
                "field": "safety",
                "reason": "Not in this synthetic source",
                "consequence": "Cannot assess safety outcomes",
            }
        ],
        "uncertainty": ["No results are available in this synthetic fixture."],
        "forecast": {
            "status": "abstain",
            "target": "Trial's fictional primary endpoint",
            "as_of": "2026-01-01",
            "horizon": "2026-07-01",
            "outcome_rule": "Resolve whether the registered primary comparison "
            "reports a two-sided p value below 0.05 by the horizon.",
            "resolution_source": "Results posted for SYNTHETIC-TRIAL-001",
            "abstention_reason": "No outcome data or defensible predictive basis.",
        },
    }


def codes(report):
    return {check.code for check in report.failed_checks}


def extraction(dossier):
    result = {
        key: deepcopy(dossier[key])
        for key in ("intervention", "indication", "population", "trials")
    }
    for trial in result["trials"]:
        del trial["source_claim_ids"]
        for item in trial["arms"] + trial["endpoints"]:
            del item["source_claim_ids"]
    return result


@pytest.fixture
def reference(dossier):
    return {
        "coverage": "complete_for_schema",
        "reference_id": "synthetic-gold-v1",
        "notes": "Synthetic comparison standard for tests only; not medical facts.",
        "extraction": extraction(dossier),
    }


def test_valid_dossier_reports_traceability_without_truth_or_confidence_grade(dossier, evidence):
    snapshot = deepcopy((dossier, evidence))
    report = validate_dossier(ClinicalDossier.model_validate(dossier), evidence)
    assert report.valid and not report.failed_checks
    assert report.coverage.trials == 1
    assert report.coverage.facts == report.coverage.inferences == 1
    assert report.coverage.verified_source_references == 2
    assert report.coverage.fully_attributed_claims == 2
    assert report.coverage.distinct_sources == 1
    assert any("not claim truth" in value for value in report.limitations)
    assert "confidence" not in report.model_dump()
    assert (dossier, evidence) == snapshot


@pytest.mark.parametrize("use_pointer", [True, False])
def test_repeated_references_hash_and_normalize_each_source_once(
    dossier, evidence, monkeypatch, use_pointer
):
    from researchdesk.research import quality

    if not use_pointer:
        for claim in dossier["claims"]:
            claim["source_refs"][0]["source_path"] = None
    hashes, selections, normalizations = [], [], []
    original_hash, original_pointer, original_normalize = (
        quality._hash,
        quality._pointer,
        quality._normalize,
    )

    def tracked_hash(content):
        hashes.append(content)
        return original_hash(content)

    def tracked_pointer(content, pointer):
        selections.append(pointer)
        return original_pointer(content, pointer)

    def tracked_normalize(text):
        normalizations.append(text)
        return original_normalize(text)

    monkeypatch.setattr(quality, "_hash", tracked_hash)
    monkeypatch.setattr(quality, "_pointer", tracked_pointer)
    monkeypatch.setattr(quality, "_normalize", tracked_normalize)
    assert validate_dossier(dossier, evidence).valid
    assert len(hashes) == 1
    assert len(selections) == (1 if use_pointer else 0)
    description = evidence["synthetic-source"]["content"]["record"]["description"]
    assert normalizations.count(description) == 1


def test_source_byte_budget_stops_before_hashing_or_claim_validation(dossier, monkeypatch):
    from researchdesk.research import quality

    artifacts, references = {}, []
    for index in range(5):
        identifier = f"large-synthetic-{index}"
        artifacts[identifier] = {
            "id": identifier,
            "kind": "evidence",
            "sha256": "0" * 64,
            "content": {"text": "x" * 1_700_000},
        }
        references.append(
            {
                "artifact_id": identifier,
                "artifact_sha256": "0" * 64,
                "excerpt": "xxx",
                "source_path": "/text",
            }
        )
    for claim in dossier["claims"]:
        claim["source_refs"] = references
    hashes = []
    monkeypatch.setattr(quality, "_hash", lambda content: hashes.append(content))
    report = validate_dossier(dossier, artifacts)
    assert not report.valid and "source_budget" in codes(report)
    assert not hashes
    assert any("incomplete" in item for item in report.limitations)


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing", "source_exists"),
        ("kind", "source_kind"),
        ("identity", "source_identity"),
        ("mutated", "source_content_integrity"),
        ("citation_hash", "source_version_match"),
    ],
)
def test_rejects_missing_wrong_kind_or_mutated_evidence(dossier, evidence, change, expected):
    if change == "missing":
        evidence.clear()
    elif change == "kind":
        evidence["synthetic-source"]["kind"] = "note"
    elif change == "identity":
        evidence["synthetic-source"]["id"] = "different-id"
    elif change == "mutated":
        evidence["synthetic-source"]["content"]["record"]["description"] += " Added text."
    else:
        dossier["claims"][0]["source_refs"][0]["artifact_sha256"] = "0" * 64
    report = validate_dossier(dossier, evidence)
    assert not report.valid and expected in codes(report)


def test_nested_source_hash_cannot_substitute_for_full_artifact_hash(dossier, evidence):
    source = evidence["synthetic-source"]
    nested_hash = content_hash(source["content"]["record"])
    source["sha256"] = nested_hash
    dossier["claims"][0]["source_refs"][0]["artifact_sha256"] = nested_hash
    assert {"source_content_integrity", "source_version_match"} <= codes(
        validate_dossier(dossier, evidence)
    )


def test_invalid_non_json_source_returns_failures_without_traversing_cycles(dossier, evidence):
    source = evidence["synthetic-source"]
    source["content"]["cycle"] = source["content"]
    for claim in dossier["claims"]:
        claim["source_refs"][0]["source_path"] = None
    report = validate_dossier(dossier, evidence)
    assert not report.valid and "source_content_integrity" in codes(report)


def test_quote_normalizes_whitespace_but_not_case_or_assertion(dossier, evidence):
    ref = dossier["claims"][0]["source_refs"][0]
    ref["excerpt"] = "Test B.   The prespecified primary endpoint"
    assert validate_dossier(dossier, evidence).valid
    ref["excerpt"] = "test b. The prespecified primary endpoint"
    assert "quote_present" in codes(validate_dossier(dossier, evidence))


@pytest.mark.parametrize(
    "quote",
    [
        '"description": "The fictional trial',
        "description",
        "week 12. Synthetic safety data",
        "The fictional trial randomized 400 adults",
    ],
)
def test_serialized_json_keys_joined_fields_and_changed_numbers_are_not_quotes(
    dossier, evidence, quote
):
    ref = dossier["claims"][0]["source_refs"][0]
    ref["source_path"] = None
    ref["excerpt"] = quote
    assert "quote_present" in codes(validate_dossier(dossier, evidence))


def test_json_pointer_escape_and_missing_or_nontext_path(dossier, evidence):
    ref = dossier["claims"][0]["source_refs"][0]
    ref.update(source_path="/record/a~1b/tilde~0key", excerpt="Synthetic safety data")
    assert validate_dossier(dossier, evidence).valid
    for path in ("/record", "/record/no-such-field", "record/description", "/record/a~2b"):
        ref["source_path"] = path
        assert "source_path_is_text" in codes(validate_dossier(dossier, evidence))


def test_inference_requires_explanation_and_remains_unverified_truth(dossier, evidence):
    dossier["claims"][1]["inference_basis"] = None
    assert "inference_basis_required" in codes(validate_dossier(dossier, evidence))
    dossier["claims"][1]["inference_basis"] = "An explicitly unverified interpretive step."
    dossier["claims"][1]["statement"] = "An unsupported interpretation used for a negative test."
    report = validate_dossier(dossier, evidence)
    assert report.valid  # Quote matching deliberately is not an entailment classifier.
    assert any("inference" in text for text in report.limitations)


def test_dangling_and_orphan_claim_trial_references_are_explicit(dossier, evidence):
    dossier["trials"][0]["endpoints"][0]["source_claim_ids"] = ["missing-claim"]
    dossier["trials"][0]["source_claim_ids"] = ["c1"]
    dossier["claims"][0]["trial_ids"] = ["wrong-trial"]
    report = validate_dossier(dossier, evidence)
    assert {
        "claim_reference_exists",
        "claim_not_orphaned",
        "claim_trial_binding",
        "trial_reference_exists",
    } <= codes(report)


def test_duplicate_identity_and_unknown_contrary_claim_fail(dossier, evidence):
    dossier["claims"].append(deepcopy(dossier["claims"][0]))
    dossier["trials"][0]["arms"].append(deepcopy(dossier["trials"][0]["arms"][0]))
    dossier["contrary_evidence_claim_ids"] = ["missing"]
    assert {"unique_claim_ids", "unique_arms_ids", "claim_reference_exists"} <= codes(
        validate_dossier(dossier, evidence)
    )


@pytest.mark.parametrize("field", ["trials", "claims", "uncertainty"])
def test_required_collections_cannot_be_empty(dossier, evidence, field):
    dossier[field] = []
    report = validate_dossier(dossier, evidence)
    assert not report.valid
    assert any(check.path == f"/{field}" for check in report.failed_checks)


def test_abstention_and_forecast_are_mutually_consistent_and_time_bounded(dossier, evidence):
    forecast = dossier["forecast"]
    forecast.update(
        horizon="2025-01-01", prediction="An answer", probability=0.7, abstention_reason=None
    )
    assert {
        "forecast_horizon",
        "abstention_reason_required",
        "abstention_has_no_prediction",
    } <= codes(validate_dossier(dossier, evidence))
    forecast.update(
        horizon="2026-07-01", status="forecast", prediction=None, abstention_reason="Cannot answer"
    )
    assert {"forecast_prediction_required", "forecast_has_no_abstention"} <= codes(
        validate_dossier(dossier, evidence)
    )
    forecast.update(
        prediction="The synthetic outcome rule will not be met.",
        abstention_reason=None,
        probability=None,
    )
    assert validate_dossier(dossier, evidence).valid


def test_boolean_probability_is_not_a_numeric_forecast(dossier, evidence):
    dossier["forecast"].update(
        status="forecast",
        prediction="A synthetic test prediction",
        abstention_reason=None,
        probability=True,
    )
    report = validate_dossier(dossier, evidence)
    assert not report.valid
    assert any(check.path == "/forecast/probability" for check in report.failed_checks)


def test_scoring_aligns_identifiers_and_normalizes_only_case_whitespace(dossier, reference):
    candidate = extraction(dossier)
    candidate["trials"][0]["arms"].reverse()
    candidate["population"] = "  40 FICTIONAL   adults  "
    score = score_extraction(
        ClinicalExtraction.model_validate(candidate), ExtractionReference.model_validate(reference)
    )
    assert score.valid and score.precision == score.recall == score.f1 == 1
    assert score.true_positives == score.reference_fields == score.candidate_fields
    assert not score.errors
    assert score_extraction(ClinicalDossier.model_validate(dossier), reference).precision == 1
    assert score_extraction(dossier, reference).precision == 1


def test_critical_mismatch_omission_and_extra_fact_have_hand_checked_counts(dossier, reference):
    candidate = extraction(dossier)
    total = score_extraction(candidate, reference).reference_fields
    candidate["trials"][0]["design"]["allocation"] = "nonrandomized"
    candidate["trials"][0]["endpoints"][0]["timeframe"] = None
    candidate["trials"].append({"trial_id": "SYNTHETIC-EXTRA-TRIAL"})
    score = score_extraction(candidate, reference)
    assert score.valid
    assert score.true_positives == total - 2
    assert score.false_positives == score.false_negatives == 2
    assert score.precision == score.recall == (total - 2) / total
    assert len(score.critical_errors) == 3
    assert {error.code for error in score.errors} == {
        "value_mismatch",
        "missing_field",
        "unexpected_field",
    }


def test_descriptive_arm_label_mismatch_is_visible_but_not_critical(dossier, reference):
    candidate = extraction(dossier)
    candidate["trials"][0]["arms"][0]["label"] = "Different wording"
    score = score_extraction(candidate, reference)
    assert len(score.errors) == 1 and not score.critical_errors


def test_blank_candidate_and_empty_reference_do_not_receive_perfect_scores(reference):
    score = score_extraction({}, reference)
    assert score.valid and score.precision is None and score.recall == 0 and score.f1 == 0
    assert score.false_negatives == score.reference_fields
    reference["extraction"] = {}
    score = score_extraction({}, reference)
    assert not score.valid and score.precision is None and score.recall is None
    assert "empty_reference" in {error.code for error in score.schema_errors}


def test_duplicate_trial_or_arm_ids_cannot_inflate_scores(dossier, reference):
    candidate = extraction(dossier)
    candidate["trials"].append(deepcopy(candidate["trials"][0]))
    score = score_extraction(candidate, reference)
    assert not score.valid and score.precision is None
    assert "duplicate_trial_id" in {error.code for error in score.schema_errors}
    candidate["trials"].pop()
    candidate["trials"][0]["arms"].append(deepcopy(candidate["trials"][0]["arms"][0]))
    assert not score_extraction(candidate, reference).valid


def test_schema_failures_never_become_quality_scores(dossier, reference):
    candidate = extraction(dossier)
    candidate["trials"][0]["arms"][0]["planned_n"] = True
    score = score_extraction(candidate, reference)
    assert not score.valid and score.precision is None
    assert any(error.path.endswith("/planned_n") for error in score.schema_errors)
    del reference["coverage"]
    assert not score_extraction(extraction(dossier), reference).valid


def test_reference_and_candidate_are_never_modified(dossier, reference):
    snapshot = deepcopy((dossier, reference))
    score_extraction(dossier, reference)
    assert (dossier, reference) == snapshot
