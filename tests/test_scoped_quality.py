"""Synthetic instrument tests; no clinical labels, model runs, or quality claims."""

from copy import deepcopy

import pytest

from researchdesk.research import scoped_quality as quality
from researchdesk.research.observation_models import ClinicalDossierV2
from researchdesk.research.quality import _pointer, _scalar_excerpt
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.store import content_hash


def present(value):
    return {"state": "present", "value": value}


def unresolved():
    return {"state": "unresolved", "reason": "Unscored synthetic field."}


@pytest.fixture
def fixture():
    content = {
        "record": {
            "enrollment": {"count": 12, "status": "ACTUAL"},
            "hasResults": False,
            "nullable": None,
            "elsewhere": 12,
            "outcomes": [
                {
                    "groups": [{"id": "G0", "title": "Synthetic A"}],
                    "title": "Cafe\u0301 response",
                    "timeframe": " Week 4\n",
                    "type": "PRIMARY",
                    "denoms": [
                        {"units": "Participants", "counts": [{"groupId": "G0", "value": "7"}]}
                    ],
                },
                {
                    "groups": [{"id": "G0", "title": "Synthetic B"}],
                    "title": "Synthetic different outcome",
                    "denoms": [
                        {"units": "Participants", "counts": [{"groupId": "G0", "value": "3"}]}
                    ],
                },
            ],
        }
    }
    artifact = {
        "id": "local-artifact",
        "kind": "evidence",
        "content": content,
        "sha256": content_hash(content),
    }
    sources = {"stable-source": artifact}

    def anchor(path):
        return {
            "artifact_id": artifact["id"],
            "artifact_sha256": artifact["sha256"],
            "source_path": path,
        }

    def ref(path):
        raw = _pointer(content, path)
        return anchor(path) | {"excerpt": raw if isinstance(raw, str) else _scalar_excerpt(raw)}

    contexts = [
        {
            "context_id": cid,
            "trial_id": "SYNTHETIC-1",
            "trial_family_id": "SYNTHETIC-FAMILY",
            "source_id": "stable-source",
            "source_path": path,
            "kind": kind,
        }
        for cid, path, kind in (
            ("registry", "/record", "study_design"),
            ("outcome0", "/record/outcomes/0", "outcome_analysis"),
            ("outcome1", "/record/outcomes/1", "outcome_analysis"),
        )
    ]
    public_observations = [
        {"observation_id": "enrollment", "context_id": "registry", "kind": "population_count"},
        {"observation_id": "endpoint", "context_id": "outcome0", "kind": "endpoint"},
        *[
            {
                "observation_id": f"count{i}",
                "context_id": f"outcome{i}",
                "kind": "population_count",
                "endpoint_observation_id": "endpoint" if i == 0 else None,
                "group": {"container_source_path": f"/record/outcomes/{i}", "local_id": "G0"},
            }
            for i in range(2)
        ],
        *[
            {"observation_id": name, "context_id": "registry", "kind": "availability"}
            for name in ("available", "null", "absent")
        ],
    ]
    definitions = [
        ("enrollment", "count", "/record/enrollment/count", 12, "identity"),
        ("enrollment", "reported_status", "/record/enrollment/status", "actual", "lowercase_enum"),
        ("endpoint", "definition", "/record/outcomes/0/title", "Café response", "nfc_whitespace"),
        ("endpoint", "timeframe", "/record/outcomes/0/timeframe", "Week 4", "nfc_whitespace"),
        ("endpoint", "reported_role", "/record/outcomes/0/type", "primary", "lowercase_enum"),
        (
            "count0",
            "count",
            "/record/outcomes/0/denoms/0/counts/0/value",
            7,
            "canonical_digit_string",
        ),
        ("count0", "unit", "/record/outcomes/0/denoms/0/units", "Participants", "identity"),
        (
            "count1",
            "count",
            "/record/outcomes/1/denoms/0/counts/0/value",
            3,
            "canonical_digit_string",
        ),
        ("available", "available", "/record/hasResults", False, "identity"),
        ("null", "available", "/record/nullable", None, "identity"),
    ]
    fields = [
        {
            "field_id": f"{oid}.{name}",
            "observation_id": oid,
            "field_name": name,
            "source_path": path,
            "question": "Extract this declared synthetic source field.",
            "severity": "ordinary",
            "normalization": op,
        }
        for oid, name, path, _, op in definitions
    ]
    fields.append(
        {
            "field_id": "absent.available",
            "observation_id": "absent",
            "field_name": "available",
            "source_path": "/record/resultsSection",
            "question": "Report scoped key availability.",
            "severity": "ordinary",
        }
    )
    scope = MechanicalScope(
        scope_id="synthetic-scope",
        version="v1",
        case_id="case",
        sources=[{"source_id": "stable-source", "artifact_sha256": artifact["sha256"]}],
        contexts=contexts,
        observations=public_observations,
        fields=fields,
    )
    rules = [
        {
            "field_id": f"{oid}.{name}",
            "expected_state": "present",
            "expected_value": value,
            "source_id": "stable-source",
            "source_path": path,
            "normalization": op,
            "rationale": "Synthetic hand-specified instrument fixture.",
            **(
                {"source_group_path": path.rsplit("/", 1)[0] + "/groupId"}
                if oid.startswith("count") and name == "count"
                else {}
            ),
        }
        for oid, name, path, value, op in definitions
    ]
    rules.append(
        {
            "field_id": "absent.available",
            "expected_state": "source_absent",
            "source_id": "stable-source",
            "source_path": "/record",
            "missing_key": "resultsSection",
            "normalization": "identity",
            "rationale": "Synthetic object lacks the named key.",
        }
    )
    reference = MechanicalReference(
        reference_id="private-reference",
        scope_sha256=scope.sha256,
        fields=rules,
        limitations=["Synthetic fixture, not clinical gold."],
        reviewers=[
            {
                "reviewer_id": "fixture-author",
                "kind": "automated",
                "method": "Synthetic test construction",
                "notes": "PRIVATE_NOTES",
            }
        ],
    )
    observations = []
    for public in public_observations:
        oid, kind = public["observation_id"], public["kind"]
        base = {
            "observation_id": oid,
            "context_id": public["context_id"],
            "kind": kind,
            "source_refs": [],
        }
        if kind == "population_count":
            base.update(
                {
                    "group": (
                        {
                            "container": anchor(public["group"]["container_source_path"]),
                            "local_id": "G0",
                        }
                        if public.get("group")
                        else None
                    ),
                    "count": unresolved(),
                    "count_normalization": "none",
                    "count_source_ref": None,
                    "unit": unresolved(),
                    "population_definition": unresolved(),
                    "reported_stage": unresolved(),
                    "stages": unresolved(),
                    "assignment_basis": unresolved(),
                    "reported_status": unresolved(),
                    "endpoint_observation_id": "endpoint" if oid == "count0" else None,
                }
            )
        elif kind == "endpoint":
            base.update(
                {
                    name: unresolved()
                    for name in (
                        "definition",
                        "reported_role",
                        "timeframe",
                        "time_origin",
                        "population_definition",
                        "comparator_description",
                        "prespecification",
                    )
                }
            )
            base.update(
                population_count_ids=["count0"],
                groups=[{"container": anchor("/record/outcomes/0"), "local_id": "G0"}],
                prespecification_refs=[],
            )
        else:
            base.update(
                subject="registry_results",
                available=unresolved(),
                available_source_ref=None,
                scope_description="Synthetic retained source only.",
            )
        for obs_id, name, path, value, op in definitions:
            if oid != obs_id:
                continue
            base[name] = present(value)
            base["source_refs"].append(ref(path))
            if name == "count":
                base["count_source_ref"] = ref(path)
                base["count_normalization"] = (
                    "integer_from_digit_string" if op == "canonical_digit_string" else "none"
                )
            if name == "available":
                base["available_source_ref"] = ref(path)
        if oid == "absent":
            base["available"] = {
                "state": "source_absent",
                "reason": "Scoped synthetic key absent.",
                "proof": {"parent": anchor("/record"), "key": "resultsSection"},
            }
        observations.append(base)
    candidate = {
        "schema_version": "clinical-dossier.v2",
        "intervention": "Synthetic",
        "indication": "Synthetic",
        "population": "Synthetic",
        "trials": [{"trial_id": "SYNTHETIC-1", "trial_family_id": "SYNTHETIC-FAMILY"}],
        "contexts": [
            {
                "context_id": c["context_id"],
                "trial_id": c["trial_id"],
                "kind": c["kind"],
                "source": anchor(c["source_path"]),
                "label": "Synthetic context.",
            }
            for c in contexts
        ],
        "observations": observations,
        "reconciliations": [],
        "claims": [
            {
                "id": "synthetic-claim",
                "kind": "fact",
                "statement": "Synthetic",
                "trial_ids": ["SYNTHETIC-1"],
                "source_refs": [ref("/record/outcomes/1/title")],
            }
        ],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "Synthetic fixture only.",
        "missing_inputs": [],
        "uncertainty": ["Synthetic."],
        "forecast": None,
    }
    return candidate, scope.model_dump(mode="json"), reference.model_dump(mode="json"), sources


def score(fixture):
    return quality.score_mechanical_dossier(*fixture)


def observation(fixture, identifier):
    return next(o for o in fixture[0]["observations"] if o["observation_id"] == identifier)


def outcomes(report):
    return {r["field_id"]: r["status"] for r in report["field_results"]}


def test_absence_cannot_simultaneously_supply_a_present_value_citation(fixture):
    observation(fixture, "absent")["available_source_ref"] = observation(fixture, "available")[
        "available_source_ref"
    ]
    report = score(fixture)
    assert outcomes(report)["absent.available"] == "invalid_record"
    assert report["matched_fields"] == report["expected_fields"] - 1


def rebind_scope(fixture):
    fixture[2]["scope_sha256"] = MechanicalScope.model_validate(fixture[1]).sha256


def rehash(fixture):
    source = fixture[3]["stable-source"]
    source["sha256"] = content_hash(source["content"])
    fixture[1]["sources"][0]["artifact_sha256"] = source["sha256"]
    rebind_scope(fixture)


def test_real_comparator_preserves_fixed_scope_and_has_no_quality_claim(fixture):
    quality.validate_mechanical_reference(*fixture[1:])
    report = score(fixture)
    assert report["matched_fields"] == report["expected_fields"] == 11
    assert report["delivered_scoped_fraction"] == report["conditional_value_agreement"] == 1
    assert report["candidate_validation"]["schema_valid"] is True
    assert report["review_count"] == 1
    assert "PRIVATE_NOTES" not in str(report)
    assert "expected_value" not in str(report)
    assert any("not clinical truth" in line for line in report["limitations"])
    fixture = (ClinicalDossierV2.model_validate(fixture[0]), *fixture[1:])
    assert score(fixture)["matched_fields"] == 11


@pytest.mark.parametrize(
    "field,value", [("kind", "evaluation_reference"), ("sha256", "f" * 64), ("id", None)]
)
def test_invalid_evaluator_source_is_an_exception_not_zero(fixture, field, value):
    fixture[3]["stable-source"][field] = value
    with pytest.raises(quality.ReferenceValidationError):
        score(fixture)


@pytest.mark.parametrize(
    "mutation",
    [
        "content",
        "scope_hash",
        "field_omitted",
        "field_extra",
        "duplicate",
        "wrong_expected",
        "wrong_path",
        "other_source",
    ],
)
def test_bad_private_reference_never_produces_candidate_score(fixture, mutation):
    _, scope, reference, sources = fixture
    if mutation == "content":
        sources["stable-source"]["content"]["corrupt"] = True
    elif mutation == "scope_hash":
        reference["scope_sha256"] = "f" * 64
    elif mutation == "field_omitted":
        reference["fields"].pop()
    elif mutation == "field_extra":
        reference["fields"].append(reference["fields"][0] | {"field_id": "extra"})
    elif mutation == "duplicate":
        reference["fields"].append(deepcopy(reference["fields"][0]))
    elif mutation == "wrong_expected":
        reference["fields"][0]["expected_value"] = 19
    elif mutation == "wrong_path":
        reference["fields"][0]["source_path"] = "/missing"
    else:
        reference["fields"][0]["source_id"] = "other"
    with pytest.raises(quality.ReferenceValidationError) as raised:
        score(fixture)
    assert "PRIVATE_NOTES" not in str(raised.value)


@pytest.mark.parametrize("value", [False, True, "12", 12.0, None])
def test_count_raw_types_do_not_coerce(fixture, value):
    observation(fixture, "enrollment")["count"]["value"] = value
    result = score(fixture)
    assert outcomes(result)["enrollment.count"] != "matched"
    assert result["matched_fields"] == 10


@pytest.mark.parametrize("value", [0, "false", None, True])
def test_boolean_and_literal_null_are_distinct(fixture, value):
    observation(fixture, "available")["available"]["value"] = value
    assert outcomes(score(fixture))["available.available"] != "matched"


@pytest.mark.parametrize(
    "key,change",
    [
        ("artifact_id", "other"),
        ("artifact_sha256", "f" * 64),
        ("source_path", "/record/elsewhere"),
        ("excerpt", "999"),
    ],
)
def test_correct_value_with_wrong_dedicated_citation_fails(fixture, key, change):
    observation(fixture, "enrollment")["count_source_ref"][key] = change
    result = score(fixture)
    assert outcomes(result)["enrollment.count"] == "unattributed"
    assert result["conditional_value_agreement"] == 1
    assert result["matched_fields"] == 10


@pytest.mark.parametrize(
    "change",
    [
        "context_hash",
        "context_path",
        "context_kind",
        "trial_family",
        "group_owner",
        "local_group",
        "observation_context",
    ],
)
def test_public_identity_is_required_not_just_matching_values(fixture, change):
    candidate = fixture[0]
    if change == "context_hash":
        candidate["contexts"][1]["source"]["artifact_sha256"] = "f" * 64
    elif change == "context_path":
        candidate["contexts"][1]["source"]["source_path"] = "/record/outcomes/1"
    elif change == "context_kind":
        candidate["contexts"][1]["kind"] = "other"
    elif change == "trial_family":
        candidate["trials"][0]["trial_family_id"] = "wrong"
    elif change == "group_owner":
        observation(fixture, "count0")["group"]["container"]["source_path"] = "/record/outcomes/1"
    elif change == "local_group":
        observation(fixture, "count0")["group"]["local_id"] = "G1"
    else:
        observation(fixture, "count0")["context_id"] = "outcome1"
    assert outcomes(score(fixture))["count0.count"] == "identity_error"


@pytest.mark.parametrize(
    "mutation",
    ["missing_field", "missing_observation", "duplicate_observation", "duplicate_context"],
)
def test_local_failures_do_not_erase_unrelated_fields(fixture, mutation):
    if mutation == "missing_field":
        del observation(fixture, "count0")["count"]
    elif mutation == "missing_observation":
        fixture[0]["observations"].remove(observation(fixture, "count0"))
    elif mutation == "duplicate_observation":
        fixture[0]["observations"].append(deepcopy(observation(fixture, "count0")))
    else:
        fixture[0]["contexts"].append(deepcopy(fixture[0]["contexts"][1]))
    result = score(fixture)
    assert result["expected_fields"] == 11
    assert outcomes(result)["count0.count"] != "matched"
    assert outcomes(result)["count1.count"] == "matched"
    assert outcomes(result)["available.available"] == "matched"


def test_unrelated_bad_extra_and_reordering_do_not_change_scoped_score(fixture):
    fixture[0]["observations"] += [{"observation_id": "unscored", "broken": True}] * 2
    fixture[0]["observations"].reverse()
    report = score(fixture)
    assert report["expected_fields"] == report["matched_fields"] == 11
    assert report["candidate_validation"]["schema_valid"] is False


@pytest.mark.parametrize("value", ["07", " 7", "7.0", "+7", "٧", "７", "7\n"])
def test_reference_integer_string_rule_is_canonical_ascii(fixture, value):
    fixture[3]["stable-source"]["content"]["record"]["outcomes"][0]["denoms"][0]["counts"][0][
        "value"
    ] = value
    rehash(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="noncanonical_integer_string"):
        score(fixture)


def test_declared_nfc_whitespace_only_and_no_synonyms(fixture):
    observation(fixture, "endpoint")["definition"] = present("  Cafe\u0301\nresponse ")
    assert outcomes(score(fixture))["endpoint.definition"] == "matched"
    observation(fixture, "endpoint")["timeframe"] = present("4 weeks")
    assert outcomes(score(fixture))["endpoint.timeframe"] == "wrong_value"
    observation(fixture, "count0")["unit"] = present("participants")
    assert outcomes(score(fixture))["count0.unit"] == "wrong_value"


@pytest.mark.parametrize(
    "mutation",
    ["group_id", "no_group_selector", "different_parent", "value_selector", "duplicate_group"],
)
def test_private_count_requires_actual_sibling_group_identity(fixture, mutation):
    rule = next(r for r in fixture[2]["fields"] if r["field_id"] == "count0.count")
    outcome = fixture[3]["stable-source"]["content"]["record"]["outcomes"][0]
    if mutation == "group_id":
        outcome["denoms"][0]["counts"][0]["groupId"] = "G1"
        rehash(fixture)
    elif mutation == "no_group_selector":
        rule["source_group_path"] = None
    elif mutation == "different_parent":
        rule["source_group_path"] = "/record/outcomes/1/denoms/0/counts/0/groupId"
    elif mutation == "value_selector":
        rule["source_group_path"] = rule["source_path"]
    else:
        outcome["groups"].append(deepcopy(outcome["groups"][0]))
        rehash(fixture)
    with pytest.raises(quality.ReferenceValidationError):
        score(fixture)


@pytest.mark.parametrize("parent", [None, [], "text", 0, {"resultsSection": None}])
def test_reference_absence_requires_existing_object_and_absent_key(fixture, parent):
    fixture[3]["stable-source"]["content"]["proofParent"] = parent
    fixture[2]["fields"][-1]["source_path"] = "/proofParent"
    fixture[1]["fields"][-1]["source_path"] = "/proofParent/resultsSection"
    # Use root context so this test isolates parent/type failure from scope failure.
    fixture[1]["contexts"][0]["source_path"] = ""
    rehash(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="missing_key_not_proven"):
        score(fixture)


def test_candidate_absence_proof_cannot_select_another_empty_location(fixture):
    observation(fixture, "absent")["available"]["proof"]["key"] = "differentKey"
    report = score(fixture)
    assert outcomes(report)["absent.available"] == "unattributed"
    observation(fixture, "absent")["available"] = unresolved()
    assert outcomes(score(fixture))["absent.available"] == "wrong_state"


def test_fresh_store_artifact_ids_are_resolved_without_changing_frozen_reference(fixture):
    before = MechanicalReference.model_validate(fixture[2]).sha256
    fixture[3]["stable-source"]["id"] = "fresh-store-artifact"

    def update(value):
        if isinstance(value, dict):
            if value.get("artifact_id") == "local-artifact":
                value["artifact_id"] = "fresh-store-artifact"
            for item in value.values():
                update(item)
        elif isinstance(value, list):
            for item in value:
                update(item)

    update(fixture[0])
    assert score(fixture)["matched_fields"] == 11
    assert MechanicalReference.model_validate(fixture[2]).sha256 == before


@pytest.mark.parametrize(
    "candidate,status",
    [
        (None, "no_submission"),
        ({}, "invalid_output"),
        ([], "invalid_output"),
        ("{broken", "invalid_output"),
    ],
)
def test_whole_attempt_failure_retains_every_required_field(fixture, candidate, status):
    result = score((candidate, *fixture[1:]))
    assert result["status"] == status
    assert result["expected_fields"] == len(result["field_results"]) == 11
    assert result["matched_fields"] == result["delivered_scoped_fraction"] == 0
    assert result["conditional_value_agreement"] is None


@pytest.mark.parametrize("which", ["candidate", "scope", "reference", "sources"])
def test_byte_budgets_stop_processing(fixture, monkeypatch, which):
    name = {
        "candidate": "MAX_CANDIDATE_BYTES",
        "scope": "MAX_SCOPE_BYTES",
        "reference": "MAX_REFERENCE_BYTES",
        "sources": "MAX_SOURCE_BYTES",
    }[which]
    monkeypatch.setattr(quality, name, 10)
    if which == "candidate":
        assert score(fixture)["status"] == "invalid_output"
    else:
        with pytest.raises(quality.ReferenceValidationError):
            score(fixture)


def test_sources_hash_once_for_repeated_field_references(fixture, monkeypatch):
    calls = []
    original = quality._hash
    monkeypatch.setattr(quality, "_hash", lambda value: (calls.append(value), original(value))[1])
    assert score(fixture)["matched_fields"] == 11
    assert len(calls) == 1


def test_reference_scalar_cannot_be_smuggled_into_list_field(fixture):
    fixture[1]["fields"][0]["field_name"] = "stages"
    rebind_scope(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="unrepresentable_expected_value"):
        score(fixture)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_link",
        "wrong_link",
        "missing_reciprocal",
        "duplicate_member",
        "missing_group",
        "wrong_context",
        "duplicate_endpoint",
    ],
)
def test_endpoint_dependency_failures_only_affect_dependent_population(fixture, mutation):
    population, endpoint = observation(fixture, "count0"), observation(fixture, "endpoint")
    if mutation == "missing_link":
        population.pop("endpoint_observation_id")
    elif mutation == "wrong_link":
        population["endpoint_observation_id"] = "different"
    elif mutation == "missing_reciprocal":
        endpoint["population_count_ids"] = []
    elif mutation == "duplicate_member":
        endpoint["population_count_ids"] = ["count0", " count0 "]
    elif mutation == "missing_group":
        endpoint["groups"] = []
    elif mutation == "wrong_context":
        endpoint["context_id"] = "outcome1"
    else:
        fixture[0]["observations"].append(deepcopy(endpoint))
    report = score(fixture)
    assert outcomes(report)["count0.count"] in {"identity_error", "ambiguous"}
    assert outcomes(report)["count1.count"] == "matched"
    assert outcomes(report)["enrollment.count"] == "matched"


def test_private_selector_and_normalization_cannot_be_undisclosed(fixture):
    fixture[2]["fields"][0]["source_path"] = (
        "/record/elsewhere"  # Same integer, wrong public selector.
    )
    with pytest.raises(quality.ReferenceValidationError, match="field_selector_not_public"):
        score(fixture)
    fixture[2]["fields"][0]["source_path"] = "/record/enrollment/count"
    fixture[1]["fields"][1]["normalization"] = "identity"
    rebind_scope(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="normalization_not_public"):
        score(fixture)


def test_absence_public_pointer_preserves_escaped_key_and_whitespace(fixture):
    rule = fixture[2]["fields"][-1]
    rule["missing_key"] = " missing~/key "
    fixture[1]["fields"][-1]["source_path"] = "/record/ missing~0~1key "
    observation(fixture, "absent")["available"]["proof"]["key"] = " missing~/key "
    rebind_scope(fixture)
    assert outcomes(score(fixture))["absent.available"] == "matched"
    fixture[1]["fields"][-1]["source_path"] = "/record/missing~0~1key"
    rebind_scope(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="field_selector_not_public"):
        score(fixture)


def test_logical_id_whitespace_matches_v2_and_duplicate_detection(fixture):
    observation(fixture, "enrollment")["observation_id"] = " enrollment "
    observation(fixture, "count0")["context_id"] = " outcome0 "
    assert score(fixture)["matched_fields"] == 11
    duplicate = deepcopy(fixture[0]["observations"][0])
    duplicate["observation_id"] = "enrollment"
    fixture[0]["observations"].append(duplicate)
    assert outcomes(score(fixture))["enrollment.count"] == "ambiguous"


def test_dedicated_count_quote_does_not_need_duplicate_generic_quote(fixture):
    enrollment = observation(fixture, "enrollment")
    enrollment["source_refs"] = [enrollment["source_refs"][1]]  # The status citation is legitimate.
    assert outcomes(score(fixture))["enrollment.count"] == "matched"


def test_source_count_admission_precedes_hashing(fixture, monkeypatch):
    sources = {f"source-{i}": {} for i in range(31)}
    monkeypatch.setattr(quality, "_hash", lambda _: pytest.fail("Must reject before hashing"))
    with pytest.raises(quality.ReferenceValidationError, match="source_count"):
        score((*fixture[:3], sources))


def test_candidate_source_budget_and_actual_byte_budget_retain_denominator(fixture):
    candidate = fixture[0]
    candidate["extra"] = [{"artifact_id": f"unscoped-{i}"} for i in range(31)]
    report = score(fixture)
    assert report["status"] == "invalid_output" and report["expected_fields"] == 11
    candidate["extra"] = "x" * 200_001
    assert score(fixture)["status"] == "invalid_output"


def test_report_limit_is_an_evaluator_failure(fixture, monkeypatch):
    monkeypatch.setattr(quality, "MAX_REPORT_BYTES", 10)
    with pytest.raises(quality.ReferenceValidationError, match="report_budget"):
        score(fixture)


def test_wrong_count_normalization_is_not_rescued_by_correct_integer(fixture):
    observation(fixture, "count0")["count_normalization"] = "reported_in_text"
    report = score(fixture)
    assert outcomes(report)["count0.count"] == "invalid_record"
    assert report["matched_fields"] == 10


def test_reference_wrong_raw_boolean_type_is_not_zero_equivalence(fixture):
    fixture[3]["stable-source"]["content"]["record"]["hasResults"] = 0
    rehash(fixture)
    with pytest.raises(quality.ReferenceValidationError, match="expected_value_not_derived"):
        score(fixture)
