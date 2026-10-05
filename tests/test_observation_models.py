"""Synthetic engineering examples only; no clinical facts or adjudicated gold labels."""

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from researchdesk.research.models import ClinicalDossier
from researchdesk.research.observation_models import (
    AvailabilityObservation,
    ClinicalDossierV2,
    ClinicalObservation,
    DesignObservation,
    EndpointObservation,
    FieldValue,
    GroupLocator,
    MissingKeyProof,
    PopulationCountObservation,
    Reconciliation,
    SourceAnchor,
)


def present(value):
    return {"state": "present", "value": value}


def unresolved():
    return {"state": "unresolved", "reason": "Not established by this synthetic fixture."}


@pytest.fixture
def anchor():
    return {
        "artifact_id": "synthetic-evidence",
        "artifact_sha256": "a" * 64,
        "source_path": "/record",
    }


@pytest.fixture
def ref(anchor):
    return anchor | {"source_path": "/record/text", "excerpt": "Synthetic test statement."}


@pytest.fixture
def count(ref, anchor):
    return {
        "kind": "population_count",
        "observation_id": "synthetic.flow.start",
        "context_id": "synthetic.context",
        "source_refs": [ref],
        "group": {"container": anchor, "local_id": "GROUP0"},
        "count": present(12),
        "count_normalization": "none",
        "count_source_ref": ref | {"source_path": "/record/count", "excerpt": "12"},
        "unit": present("participants"),
        "population_definition": present("Fictional randomized and dosed participants."),
        "reported_stage": present("Randomized and dosed"),
        "stages": present(["randomized", "dosed"]),
        "assignment_basis": present("as_assigned"),
        "reported_status": unresolved(),
    }


@pytest.fixture
def design(ref):
    return {
        "kind": "design",
        "observation_id": "synthetic.assignment",
        "context_id": "synthetic.context",
        "source_refs": [ref],
        "design_scope": "trial_assignment",
        "study_type": present("interventional"),
        "allocation": present("randomized"),
        "intervention_model": present("PARALLEL"),
        "masking": unresolved(),
        "phase": unresolved(),
        "comparator_source": present("concurrent_internal"),
    }


@pytest.fixture
def endpoint(ref):
    return {
        "kind": "endpoint",
        "observation_id": "synthetic.endpoint",
        "context_id": "synthetic.context",
        "source_refs": [ref],
        "definition": present("Fictional score change"),
        "reported_role": present("primary"),
        "timeframe": present("12 weeks"),
        "time_origin": present("randomization"),
        "population_definition": unresolved(),
        "comparator_description": unresolved(),
        "population_count_ids": ["synthetic.flow.start"],
        "groups": [],
        "prespecification": unresolved(),
    }


@pytest.fixture
def availability(ref):
    return {
        "kind": "availability",
        "observation_id": "synthetic.results",
        "context_id": "synthetic.context",
        "source_refs": [ref],
        "subject": "registry_results",
        "available": present(False),
        "available_source_ref": ref | {"source_path": "/record/available", "excerpt": "false"},
        "scope_description": "Retained synthetic registry snapshot only.",
    }


@pytest.fixture
def dossier_v2(anchor, ref, count, design, endpoint, availability):
    return {
        "schema_version": "clinical-dossier.v2",
        "intervention": "Synthetic intervention",
        "indication": "Synthetic indication",
        "population": "Synthetic population, not medical evidence",
        "trials": [{"trial_id": "SYNTHETIC-1", "trial_family_id": "SYNTHETIC-FAMILY"}],
        "contexts": [
            {
                "context_id": "synthetic.context",
                "trial_id": "SYNTHETIC-1",
                "source": anchor,
                "kind": "publication_analysis",
                "label": "Synthetic source context",
            }
        ],
        "observations": [design, count, endpoint, availability],
        "reconciliations": [],
        "claims": [
            {
                "id": "synthetic-claim",
                "kind": "fact",
                "statement": "Synthetic test statement.",
                "trial_ids": ["SYNTHETIC-1"],
                "source_refs": [ref],
            }
        ],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "This fixture is not a literature review.",
        "missing_inputs": [],
        "uncertainty": ["Synthetic fixture; no medical conclusion is supported."],
        "forecast": {
            "status": "abstain",
            "target": "Fictional endpoint",
            "as_of": "2026-01-01",
            "horizon": "2026-07-01",
            "outcome_rule": "Read fictional result by the horizon.",
            "resolution_source": "Synthetic evidence only",
            "abstention_reason": "Synthetic fixture cannot support a real forecast.",
        },
    }


def test_typed_ledger_round_trips_without_flattening(dossier_v2):
    dossier = ClinicalDossierV2.model_validate(dossier_v2)
    assert [type(item) for item in dossier.observations] == [
        DesignObservation,
        PopulationCountObservation,
        EndpointObservation,
        AvailabilityObservation,
    ]
    assert dossier.observations[1].stages.value == ["randomized", "dosed"]
    assert ClinicalDossierV2.model_validate_json(dossier.model_dump_json()) == dossier


@pytest.mark.parametrize("value", [0, 7])
def test_present_strict_integer_preserves_zero(value):
    assert TypeAdapter(FieldValue[int]).validate_python(present(value)).value == value


@pytest.mark.parametrize("value", [True, False, "7", 7.0, None])
def test_present_integer_rejects_coercion_and_unpermitted_null(value):
    with pytest.raises(ValidationError):
        TypeAdapter(FieldValue[int]).validate_python(present(value))


def test_present_null_is_distinct_and_requires_explicit_value():
    adapter = TypeAdapter(FieldValue[str | None])
    assert adapter.validate_python(present(None)).model_dump() == present(None)
    with pytest.raises(ValidationError):
        adapter.validate_python({"state": "present"})


@pytest.mark.parametrize("state", ["unresolved", "not_applicable"])
def test_nonpresent_value_forbidden_including_null(state):
    adapter = TypeAdapter(FieldValue[str])
    valid = {"state": state, "reason": "Synthetic missingness explanation."}
    assert "value" not in adapter.validate_python(valid).model_dump()
    with pytest.raises(ValidationError):
        adapter.validate_python(valid | {"value": None})
    with pytest.raises(ValidationError):
        adapter.validate_python({"state": state})


@pytest.mark.parametrize("state", ["unknown", "omitted", "outside_scope", "not_reported"])
def test_ambiguous_or_scorer_only_states_are_not_candidate_states(state):
    with pytest.raises(ValidationError):
        TypeAdapter(FieldValue[str]).validate_python({"state": state, "reason": "Synthetic"})


def test_source_absence_requires_exact_missing_key_assertion(anchor):
    adapter = TypeAdapter(FieldValue[str])
    absent = {
        "state": "source_absent",
        "reason": "Only the specified key is asserted absent.",
        "proof": {"parent": anchor, "key": "safety"},
    }
    parsed = adapter.validate_python(absent)
    assert parsed.proof.parent == SourceAnchor.model_validate(anchor)
    assert "value" not in parsed.model_dump()
    with pytest.raises(ValidationError):
        adapter.validate_python({key: value for key, value in absent.items() if key != "proof"})
    with pytest.raises(ValidationError):
        adapter.validate_python(absent | {"value": None})
    with pytest.raises(ValidationError):
        MissingKeyProof.model_validate({"parent": anchor, "key": ["a", "b"]})


@pytest.mark.parametrize("pointer", ["", "/", "/a~1b/~0key", "/key with space "])
def test_anchor_preserves_valid_pointer_spelling(anchor, pointer):
    parsed = SourceAnchor.model_validate(anchor | {"source_path": pointer})
    assert parsed.source_path == pointer


@pytest.mark.parametrize("pointer", ["record/value", "#/record", "/bad~2", "/bad~", 0])
def test_anchor_rejects_non_pointer_or_invalid_escape(anchor, pointer):
    with pytest.raises(ValidationError):
        SourceAnchor.model_validate(anchor | {"source_path": pointer})


def test_missing_key_preserves_empty_and_whitespace_keys(anchor):
    for key in ("", " key ", "a/b", "~"):
        assert MissingKeyProof.model_validate({"parent": anchor, "key": key}).key == key


def test_group_identity_uses_version_and_individual_container(anchor):
    first = GroupLocator.model_validate(
        {"container": anchor | {"source_path": "/outcomes/0"}, "local_id": "OG000"}
    )
    second = GroupLocator.model_validate(
        {"container": anchor | {"source_path": "/outcomes/12"}, "local_id": "OG000"}
    )
    new_version = GroupLocator.model_validate(
        {
            "container": first.container.model_dump() | {"artifact_sha256": "b" * 64},
            "local_id": "OG000",
        }
    )
    assert len({first.key, second.key, new_version.key}) == 3
    assert first.key == ("a" * 64, "/outcomes/0", "OG000")


def test_group_local_identifier_whitespace_is_source_identity(anchor):
    group = GroupLocator.model_validate({"container": anchor, "local_id": " GROUP0 "})
    assert group.local_id == " GROUP0 "
    assert group.key[-1] == " GROUP0 "


def test_population_contexts_keep_distinct_denominators(count):
    assigned = PopulationCountObservation.model_validate(count)
    actual = PopulationCountObservation.model_validate(
        count
        | {
            "observation_id": "synthetic.flow.safety",
            "count": present(10),
            "reported_stage": present("Safety set"),
            "stages": present(["safety_set"]),
            "assignment_basis": present("actual_treatment_received"),
        }
    )
    assert assigned.group.key == actual.group.key
    assert assigned.count.value == 12 and actual.count.value == 10
    assert assigned.assignment_basis != actual.assignment_basis


@pytest.mark.parametrize("value", [-1, True, "12", 12.0])
def test_population_count_is_nonnegative_strict_integer(count, value):
    with pytest.raises(ValidationError):
        PopulationCountObservation.model_validate(count | {"count": present(value)})


@pytest.mark.parametrize("stages", [[], ["dosed", "dosed"], ["unsupported_stage"]])
def test_population_stages_are_nonempty_distinct_supported_tags(count, stages):
    with pytest.raises(ValidationError):
        PopulationCountObservation.model_validate(count | {"stages": present(stages)})


def test_count_source_null_and_unresolved_remain_distinct(count):
    source_null = PopulationCountObservation.model_validate(
        count
        | {
            "count": present(None),
            "count_source_ref": count["count_source_ref"] | {"excerpt": "null"},
        }
    )
    unknown = PopulationCountObservation.model_validate(
        count | {"count": unresolved(), "count_source_ref": None}
    )
    assert source_null.count.state == "present" and source_null.count.value is None
    assert unknown.count.state == "unresolved"


def test_present_count_requires_a_specific_citation_including_null(count):
    for value in (12, None):
        with pytest.raises(ValidationError, match="requires count_source_ref"):
            PopulationCountObservation.model_validate(
                count | {"count": present(value), "count_source_ref": None}
            )
    with pytest.raises(ValidationError, match="cannot supply count_source_ref"):
        PopulationCountObservation.model_validate(count | {"count": unresolved()})


@pytest.mark.parametrize("normalization", ["integer_from_digit_string", "reported_in_text"])
def test_count_normalization_is_explicit_and_only_applies_to_numbers(count, normalization):
    normalized = PopulationCountObservation.model_validate(
        count | {"count_normalization": normalization}
    )
    assert normalized.count.value == 12
    for missing in (present(None), unresolved()):
        with pytest.raises(ValidationError):
            PopulationCountObservation.model_validate(
                count
                | {
                    "count": missing,
                    "count_normalization": normalization,
                    "count_source_ref": (
                        count["count_source_ref"] if missing["state"] == "present" else None
                    ),
                }
            )
    with pytest.raises(ValidationError):
        PopulationCountObservation.model_validate(count | {"count_normalization": "sum_of_groups"})
    with pytest.raises(ValidationError):
        PopulationCountObservation.model_validate(
            {key: value for key, value in count.items() if key != "count_normalization"}
        )


def test_trial_assignment_and_analysis_comparison_coexist(design, dossier_v2):
    compared = design | {
        "observation_id": "synthetic.external-comparison",
        "design_scope": "analysis_comparison",
        "allocation": present("nonrandomized"),
        "comparator_source": present("external"),
    }
    dossier_v2["observations"] = [design, compared]
    observations = ClinicalDossierV2.model_validate(dossier_v2).observations
    assert [item.allocation.value for item in observations] == ["randomized", "nonrandomized"]


def test_endpoint_role_does_not_infer_prespecification(endpoint, ref):
    parsed = EndpointObservation.model_validate(endpoint)
    assert parsed.reported_role.value == "primary"
    assert parsed.prespecification.state == "unresolved"
    with pytest.raises(ValidationError, match="prespecification_refs"):
        EndpointObservation.model_validate(endpoint | {"prespecification": present("yes")})
    supported_shape = endpoint | {
        "prespecification": present("yes"),
        "prespecification_refs": [ref],
    }
    assert EndpointObservation.model_validate(supported_shape).prespecification.value == "yes"


@pytest.mark.parametrize("value", [False, True, None])
def test_availability_preserves_explicit_boolean_or_source_null(availability, value):
    parsed = AvailabilityObservation.model_validate(availability | {"available": present(value)})
    assert parsed.available.value is value


@pytest.mark.parametrize("value", [0, 1, "false", "true"])
def test_availability_rejects_boolean_coercion(availability, value):
    with pytest.raises(ValidationError):
        AvailabilityObservation.model_validate(availability | {"available": present(value)})


@pytest.mark.parametrize("fixture_name", ["count", "design", "endpoint", "availability"])
def test_present_observation_facts_require_citations(request, fixture_name):
    record = request.getfixturevalue(fixture_name)
    record["source_refs"] = []
    with pytest.raises(ValidationError, match="requires source_refs"):
        TypeAdapter(ClinicalObservation).validate_python(record)


def test_unresolved_availability_does_not_require_a_manufactured_quote(availability):
    parsed = AvailabilityObservation.model_validate(
        availability | {"available": unresolved(), "source_refs": [], "available_source_ref": None}
    )
    assert parsed.available.state == "unresolved"


def test_reconciliation_requires_distinct_inputs_and_fact_or_inference_basis(ref):
    record = {
        "observation_ids": ["synthetic.enrolled", "synthetic.dosed"],
        "relationship": "compatible_contexts",
        "explanation": "Fictional populations differ by stated eligibility stage.",
        "kind": "fact",
        "source_refs": [ref],
    }
    assert Reconciliation.model_validate(record).kind == "fact"
    with pytest.raises(ValidationError):
        Reconciliation.model_validate(record | {"source_refs": []})
    with pytest.raises(ValidationError):
        Reconciliation.model_validate(record | {"observation_ids": ["same", "same"]})
    with pytest.raises(ValidationError):
        Reconciliation.model_validate(record | {"kind": "inference"})
    inferred = record | {
        "kind": "inference",
        "source_refs": [],
        "inference_basis": "Scoped reasoning",
    }
    assert Reconciliation.model_validate(inferred).kind == "inference"
    with pytest.raises(ValidationError):
        Reconciliation.model_validate(record | {"inference_basis": "Conflicting declaration"})


def test_observations_bounded_and_unknown_kinds_not_silently_accepted(dossier_v2, count):
    with pytest.raises(ValidationError):
        ClinicalDossierV2.model_validate(dossier_v2 | {"observations": [count] * 301})
    with pytest.raises(ValidationError):
        ClinicalDossierV2.model_validate(dossier_v2 | {"observations": []})
    with pytest.raises(ValidationError):
        TypeAdapter(ClinicalObservation).validate_python(count | {"kind": "custom_freeform"})


def test_version_mismatch_does_not_flatten_or_reinterpret_v1(dossier_v2):
    with pytest.raises(ValidationError):
        ClinicalDossier.model_validate(dossier_v2)
    with pytest.raises(ValidationError):
        ClinicalDossierV2.model_validate(dossier_v2 | {"schema_version": "clinical-dossier.v1"})
    assert ClinicalDossier.model_fields["schema_version"].default == "clinical-dossier.v1"


def test_json_schema_exposes_agent_discriminators_and_required_values():
    schema = ClinicalDossierV2.model_json_schema()
    assert schema["properties"]["observations"]["items"]["discriminator"]["propertyName"] == "kind"
    state_schema = TypeAdapter(FieldValue[int]).json_schema()
    assert state_schema["discriminator"]["propertyName"] == "state"
    present_schema = next(
        item
        for item in state_schema["$defs"].values()
        if item.get("properties", {}).get("state", {}).get("const") == "present"
    )
    assert "value" in present_schema["required"]
    assert "integer" == present_schema["properties"]["value"]["type"]


def test_field_omission_is_not_silently_rewritten_to_unknown(count):
    incomplete = deepcopy(count)
    del incomplete["population_definition"]
    with pytest.raises(ValidationError):
        PopulationCountObservation.model_validate(incomplete)
