"""Synthetic schema fixtures, not clinical evidence, expert gold or measured quality."""

from copy import deepcopy
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from researchdesk.research.observation_models import (
    AvailabilityObservation,
    DesignObservation,
    EndpointObservation,
    ObservationContext,
    PopulationCountObservation,
)
from researchdesk.research.scoped_models import (
    OBSERVATION_FIELDS,
    AbsentMechanicalFieldReference,
    ContextKind,
    MechanicalFieldReference,
    MechanicalReference,
    MechanicalScope,
    PresentMechanicalFieldReference,
    ReviewerRecord,
    ScopeContext,
    ScopedField,
    ScopeGroup,
    ScopeObservation,
)
from researchdesk.store import content_hash


@pytest.fixture
def scope_data():
    return {
        "scope_id": "synthetic-scope",
        "version": "v1",
        "case_id": "synthetic-case",
        "sources": [{"source_id": "synthetic-source", "artifact_sha256": "a" * 64}],
        "contexts": [
            {
                "context_id": "synthetic-context",
                "trial_id": "synthetic-trial",
                "trial_family_id": "synthetic-family",
                "source_id": "synthetic-source",
                "source_path": "/results/outcomes/0",
                "kind": "outcome_analysis",
            }
        ],
        "observations": [
            {
                "observation_id": "synthetic-count",
                "context_id": "synthetic-context",
                "kind": "population_count",
                "group": {"container_source_path": "/results/outcomes/0", "local_id": "GROUP0"},
            }
        ],
        "fields": [
            {
                "field_id": "synthetic-count-value",
                "observation_id": "synthetic-count",
                "field_name": "count",
                "source_path": "/results/outcomes/0/denoms/0/counts/0/value",
                "question": "What count is reported in the specified fictional source group?",
                "severity": "data_integrity",
            }
        ],
    }


@pytest.fixture
def present_ref():
    return {
        "field_id": "synthetic-count-value",
        "expected_state": "present",
        "expected_value": 12,
        "source_id": "synthetic-source",
        "source_path": "/results/outcomes/0/denoms/0/counts/0/value",
        "source_group_path": "/results/outcomes/0/denoms/0/counts/0/groupId",
        "normalization": "canonical_digit_string",
        "rationale": "Synthetic source projection for schema tests only.",
    }


@pytest.fixture
def absent_ref():
    return {
        "field_id": "synthetic-missing-value",
        "expected_state": "source_absent",
        "source_id": "synthetic-source",
        "source_path": "/results",
        "missing_key": "unreported",
        "normalization": "identity",
        "rationale": "Only this exact key is asserted absent in the synthetic object.",
    }


@pytest.fixture
def reference_data(scope_data, present_ref):
    return {
        "reference_id": "synthetic-reference",
        "scope_sha256": MechanicalScope.model_validate(scope_data).sha256,
        "fields": [present_ref],
        "limitations": ["Synthetic programmatic projection; not expert adjudication."],
    }


def test_scope_and_reference_roundtrip_freeze_and_bind_canonical_hash(scope_data, reference_data):
    for model, raw in [(MechanicalScope, scope_data), (MechanicalReference, reference_data)]:
        record = model.model_validate(raw)
        assert record.sha256 == content_hash(record.model_dump(mode="json"))
        assert model.model_validate_json(record.model_dump_json()).sha256 == record.sha256
        assert isinstance(record.fields, tuple)
        with pytest.raises(ValidationError, match="frozen"):
            record.fields[0].field_id = "changed"
        with pytest.raises(ValidationError, match="frozen"):
            record.fields = ()
    scope = MechanicalScope.model_validate(scope_data)
    assert isinstance(scope.sources, tuple)
    assert isinstance(scope.contexts, tuple)
    assert isinstance(scope.observations, tuple)


@pytest.mark.parametrize("field", ["question", "severity"])
def test_hash_changes_when_target_question_or_severity_changes(scope_data, field):
    old = MechanicalScope.model_validate(scope_data).sha256
    scope_data["fields"][0][field] = (
        "Changed synthetic question" if field == "question" else "ordinary"
    )
    assert MechanicalScope.model_validate(scope_data).sha256 != old


@pytest.mark.parametrize(
    "collection,key",
    [
        ("sources", "source_id"),
        ("contexts", "context_id"),
        ("observations", "observation_id"),
        ("fields", "field_id"),
    ],
)
def test_public_ids_unique_after_declared_id_trimming(scope_data, collection, key):
    duplicate = deepcopy(scope_data[collection][0])
    duplicate[key] = " " + duplicate[key] + " "
    scope_data[collection].append(duplicate)
    with pytest.raises(ValidationError, match="unique"):
        MechanicalScope.model_validate(scope_data)


def test_same_field_target_cannot_be_counted_twice_under_different_ids(scope_data):
    scope_data["fields"].append(scope_data["fields"][0] | {"field_id": "different-id"})
    with pytest.raises(ValidationError, match="Field targets"):
        MechanicalScope.model_validate(scope_data)


@pytest.mark.parametrize(
    "collection,link",
    [
        ("contexts", "source_id"),
        ("observations", "context_id"),
        ("fields", "observation_id"),
    ],
)
def test_identity_links_are_case_sensitive_and_must_resolve(scope_data, collection, link):
    scope_data[collection][0][link] = scope_data[collection][0][link].upper()
    with pytest.raises(ValidationError, match="unknown"):
        MechanicalScope.model_validate(scope_data)


def test_trial_identity_cannot_change_family_between_contexts(scope_data):
    scope_data["contexts"].append(
        scope_data["contexts"][0]
        | {
            "context_id": "another-context",
            "trial_family_id": "unrelated-family",
        }
    )
    with pytest.raises(ValidationError, match="one trial family"):
        MechanicalScope.model_validate(scope_data)


def test_group_must_use_exact_individual_context_container(scope_data):
    scope_data["observations"][0]["group"]["container_source_path"] = "/results"
    with pytest.raises(ValidationError, match="exact source container"):
        MechanicalScope.model_validate(scope_data)


def test_population_endpoint_link_is_public_and_hash_bound(scope_data):
    before = MechanicalScope.model_validate(scope_data).sha256
    scope_data["observations"].append(
        {
            "observation_id": "synthetic-endpoint",
            "context_id": "synthetic-context",
            "kind": "endpoint",
        }
    )
    scope_data["observations"][0]["endpoint_observation_id"] = "synthetic-endpoint"
    parsed = MechanicalScope.model_validate(scope_data)
    assert parsed.observations[0].endpoint_observation_id == "synthetic-endpoint"
    assert parsed.sha256 != before
    linked_hash = parsed.sha256
    del scope_data["observations"][0]["endpoint_observation_id"]
    assert MechanicalScope.model_validate(scope_data).sha256 != linked_hash


@pytest.mark.parametrize("target", ["unknown-endpoint", "synthetic-count"])
def test_population_endpoint_link_requires_existing_endpoint(scope_data, target):
    scope_data["observations"][0]["endpoint_observation_id"] = target
    with pytest.raises(ValidationError, match="name an endpoint"):
        MechanicalScope.model_validate(scope_data)


def test_population_endpoint_link_cannot_cross_source_contexts(scope_data):
    scope_data["contexts"].append(
        scope_data["contexts"][0]
        | {"context_id": "different-context", "source_path": "/results/outcomes/1"}
    )
    scope_data["observations"].append(
        {
            "observation_id": "synthetic-endpoint",
            "context_id": "different-context",
            "kind": "endpoint",
        }
    )
    scope_data["observations"][0]["endpoint_observation_id"] = "synthetic-endpoint"
    with pytest.raises(ValidationError, match="same context"):
        MechanicalScope.model_validate(scope_data)


@pytest.mark.parametrize("kind", ["design", "endpoint", "availability"])
def test_endpoint_link_only_belongs_to_population_count(kind):
    data = {
        "observation_id": "synthetic-observation",
        "context_id": "synthetic-context",
        "kind": kind,
        "endpoint_observation_id": "synthetic-endpoint",
    }
    if kind == "design":
        data["design_scope"] = "trial_assignment"
    with pytest.raises(ValidationError, match="Only population_count"):
        ScopeObservation.model_validate(data)


@pytest.mark.parametrize(
    "normalization", ["identity", "canonical_digit_string", "lowercase_enum", "nfc_whitespace"]
)
def test_normalization_is_public_and_hash_bound(scope_data, normalization):
    default = MechanicalScope.model_validate(scope_data)
    assert default.fields[0].normalization == "identity"
    scope_data["fields"][0]["normalization"] = normalization
    declared = MechanicalScope.model_validate(scope_data)
    assert declared.model_dump(mode="json")["fields"][0]["normalization"] == normalization
    assert (declared.sha256 == default.sha256) is (normalization == "identity")


def test_unknown_public_normalization_is_rejected(scope_data):
    scope_data["fields"][0]["normalization"] = "infer_from_expected_answer"
    with pytest.raises(ValidationError):
        MechanicalScope.model_validate(scope_data)


@pytest.mark.parametrize("kind", ["design", "endpoint", "availability"])
def test_group_only_belongs_to_population_count(scope_data, kind):
    observation = scope_data["observations"][0] | {"kind": kind}
    if kind == "design":
        observation["design_scope"] = "trial_assignment"
    with pytest.raises(ValidationError, match="Only population_count"):
        ScopeObservation.model_validate(observation)


def test_design_scope_is_required_exactly_for_design(scope_data):
    observation = {
        key: value for key, value in scope_data["observations"][0].items() if key != "group"
    }
    with pytest.raises(ValidationError, match="require design_scope"):
        ScopeObservation.model_validate(observation | {"kind": "design"})
    for scope in ("trial_assignment", "analysis_comparison"):
        parsed = ScopeObservation.model_validate(
            observation | {"kind": "design", "design_scope": scope}
        )
        assert parsed.design_scope == scope
    with pytest.raises(ValidationError, match="Only design"):
        ScopeObservation.model_validate(observation | {"design_scope": "trial_assignment"})


def test_field_must_be_a_fieldvalue_target_of_its_observation_kind(scope_data):
    scope_data["fields"][0]["field_name"] = "allocation"
    with pytest.raises(ValidationError, match="not a FieldValue field"):
        MechanicalScope.model_validate(scope_data)
    for invalid in ("source_refs", "observation_id", "count_normalization", "count/value"):
        with pytest.raises(ValidationError):
            ScopedField.model_validate(scope_data["fields"][0] | {"field_name": invalid})


def test_scope_field_allowlist_matches_existing_fieldvalue_wrappers():
    models = {
        "design": DesignObservation,
        "population_count": PopulationCountObservation,
        "endpoint": EndpointObservation,
        "availability": AvailabilityObservation,
    }
    for kind, model in models.items():
        actual = {
            name
            for name, field in model.model_fields.items()
            if str(field.annotation).startswith("FieldValue[")
        }
        assert OBSERVATION_FIELDS[kind] == actual
    assert set(get_args(ContextKind)) == set(
        get_args(ObservationContext.model_fields["kind"].annotation)
    )


@pytest.mark.parametrize(
    "collection,maximum",
    [
        ("sources", 30),
        ("contexts", 150),
        ("observations", 300),
        ("fields", 1000),
    ],
)
def test_scope_collection_bounds(scope_data, collection, maximum):
    for values in ([], [scope_data[collection][0]] * (maximum + 1)):
        with pytest.raises(ValidationError):
            MechanicalScope.model_validate(scope_data | {collection: values})


@pytest.mark.parametrize(
    "secret", ["expected_value", "reference_id", "reference_sha256", "rationale"]
)
def test_public_contract_forbids_private_answer_and_reference_fields(scope_data, secret):
    with pytest.raises(ValidationError):
        MechanicalScope.model_validate(scope_data | {secret: "private"})
    scope_data["fields"][0][secret] = "private"
    with pytest.raises(ValidationError):
        MechanicalScope.model_validate(scope_data)


def test_public_ids_trim_but_source_locations_and_group_ids_preserve_whitespace(scope_data):
    scope_data["sources"][0]["source_id"] = " synthetic-source "
    scope_data["contexts"][0]["context_id"] = " synthetic-context "
    scope_data["contexts"][0]["source_path"] = "/record/a~1b/key "
    scope_data["fields"][0]["source_path"] = "/record/a~1b/key / value "
    scope_data["observations"][0]["group"] = {
        "container_source_path": "/record/a~1b/key ",
        "local_id": " GROUP0 ",
    }
    scope = MechanicalScope.model_validate(scope_data)
    assert scope.sources[0].source_id == "synthetic-source"
    assert scope.contexts[0].context_id == "synthetic-context"
    assert scope.contexts[0].source_path == "/record/a~1b/key "
    assert scope.observations[0].group.local_id == " GROUP0 "
    assert scope.fields[0].source_path == "/record/a~1b/key / value "


def test_public_field_selector_required_and_hash_bound(scope_data):
    original = MechanicalScope.model_validate(scope_data).sha256
    scope_data["fields"][0]["source_path"] += "2"
    assert MechanicalScope.model_validate(scope_data).sha256 != original
    del scope_data["fields"][0]["source_path"]
    with pytest.raises(ValidationError, match="source_path"):
        MechanicalScope.model_validate(scope_data)


@pytest.mark.parametrize("path", ["/results/outcomes/01/count", "/elsewhere/count"])
def test_public_field_selector_cannot_leave_owning_context(scope_data, path):
    scope_data["fields"][0]["source_path"] = path
    with pytest.raises(ValidationError, match="within its source context"):
        MechanicalScope.model_validate(scope_data)


@pytest.mark.parametrize("pointer", ["", "/", "/a~1b/~0key", "/ key "])
def test_valid_exact_source_pointers(scope_data, present_ref, pointer):
    assert (
        ScopeContext.model_validate(
            scope_data["contexts"][0] | {"source_path": pointer}
        ).source_path
        == pointer
    )
    assert (
        PresentMechanicalFieldReference.model_validate(
            present_ref | {"source_path": pointer}
        ).source_path
        == pointer
    )


@pytest.mark.parametrize("pointer", ["no-leading-slash", "#/record", "/bad~2", "/bad~", 0])
def test_invalid_pointer_forms_rejected(scope_data, present_ref, pointer):
    with pytest.raises(ValidationError):
        ScopeContext.model_validate(scope_data["contexts"][0] | {"source_path": pointer})
    with pytest.raises(ValidationError):
        PresentMechanicalFieldReference.model_validate(present_ref | {"source_group_path": pointer})


@pytest.mark.parametrize("value", [False, True, 0, -2, 12, None, "", "  ", " mixed CASE \n"])
def test_identity_expected_values_preserve_exact_type_and_text(present_ref, value):
    raw = present_ref | {"expected_value": value, "normalization": "identity"}
    result = PresentMechanicalFieldReference.model_validate(raw)
    assert type(result.expected_value) is type(value)
    assert result.expected_value == value
    assert PresentMechanicalFieldReference.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("value", [1.0, 0.0, float("nan"), float("inf"), [], {}, ["dosed"]])
def test_present_references_reject_floats_and_composite_values(present_ref, value):
    with pytest.raises(ValidationError):
        PresentMechanicalFieldReference.model_validate(
            present_ref | {"expected_value": value, "normalization": "identity"}
        )


@pytest.mark.parametrize("value", [-1, True, False, "12", None])
def test_digit_string_normalization_requires_nonnegative_integer_not_bool(present_ref, value):
    with pytest.raises(ValidationError, match="nonnegative strict integer"):
        PresentMechanicalFieldReference.model_validate(present_ref | {"expected_value": value})
    assert (
        PresentMechanicalFieldReference.model_validate(
            present_ref | {"expected_value": 0}
        ).expected_value
        == 0
    )


@pytest.mark.parametrize("normalization", ["lowercase_enum", "nfc_whitespace"])
def test_text_normalizers_require_strings_and_allow_empty_normalized_output(
    present_ref, normalization
):
    for value in (False, 0, None):
        with pytest.raises(ValidationError, match="requires a string"):
            PresentMechanicalFieldReference.model_validate(
                present_ref | {"expected_value": value, "normalization": normalization}
            )
    assert (
        PresentMechanicalFieldReference.model_validate(
            present_ref | {"expected_value": "", "normalization": normalization}
        ).expected_value
        == ""
    )


def test_present_requires_value_key_including_explicit_null_and_forbids_missing_key(present_ref):
    with pytest.raises(ValidationError):
        PresentMechanicalFieldReference.model_validate(
            {key: value for key, value in present_ref.items() if key != "expected_value"}
        )
    for missing_key in (None, "key"):
        with pytest.raises(ValidationError):
            PresentMechanicalFieldReference.model_validate(
                present_ref | {"missing_key": missing_key}
            )


def test_absence_is_an_exact_missing_key_assertion_without_value_or_group_selector(absent_ref):
    adapter = TypeAdapter(MechanicalFieldReference)
    for key in ("", " key ", "a/b~"):
        parsed = adapter.validate_python(absent_ref | {"missing_key": key})
        assert isinstance(parsed, AbsentMechanicalFieldReference)
        assert parsed.missing_key == key
        assert "expected_value" not in parsed.model_dump()
        assert "source_group_path" not in parsed.model_dump()
    for forbidden in (
        {"expected_value": None},
        {"source_group_path": None},
        {"normalization": "nfc_whitespace"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(absent_ref | forbidden)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {key: value for key, value in absent_ref.items() if key != "missing_key"}
        )


@pytest.mark.parametrize("state", ["unresolved", "not_applicable", "unknown"])
def test_initial_reference_scope_excludes_unscored_states(present_ref, state):
    with pytest.raises(ValidationError):
        TypeAdapter(MechanicalFieldReference).validate_python(
            present_ref | {"expected_state": state}
        )


def test_source_null_and_absence_have_distinct_reference_serialization(present_ref, absent_ref):
    present = TypeAdapter(MechanicalFieldReference).validate_python(
        present_ref | {"expected_value": None, "normalization": "identity"}
    )
    absent = TypeAdapter(MechanicalFieldReference).validate_python(absent_ref)
    assert "expected_value" in present.model_dump()
    assert "expected_value" not in absent.model_dump()


def test_false_and_zero_bind_different_hashes(present_ref):
    false = PresentMechanicalFieldReference.model_validate(
        present_ref | {"expected_value": False, "normalization": "identity"}
    )
    zero = PresentMechanicalFieldReference.model_validate(
        present_ref | {"expected_value": 0, "normalization": "identity"}
    )
    assert false.sha256 != zero.sha256


def test_reference_fields_are_unique_and_bounded(reference_data, present_ref):
    with pytest.raises(ValidationError, match="unique"):
        MechanicalReference.model_validate(reference_data | {"fields": [present_ref, present_ref]})
    for fields in ([], [present_ref] * 1001):
        with pytest.raises(ValidationError):
            MechanicalReference.model_validate(reference_data | {"fields": fields})


@pytest.mark.parametrize("limitations", [[], [""], ["   "], ["limit"] * 101])
def test_reference_requires_bounded_nonblank_limitations(reference_data, limitations):
    with pytest.raises(ValidationError):
        MechanicalReference.model_validate(reference_data | {"limitations": limitations})


def test_reference_metadata_cannot_claim_complete_schema_or_expert_adjudication(reference_data):
    for extra in ({"coverage": "complete_for_schema"}, {"method": "independently_adjudicated"}):
        with pytest.raises(ValidationError):
            MechanicalReference.model_validate(reference_data | extra)
    record = MechanicalReference.model_validate(reference_data)
    assert record.method == "programmatic_source_projection"
    assert record.reviewers == ()


def test_reviewer_records_attribute_review_but_cannot_self_assert_trust(reference_data):
    review = {
        "reviewer_id": "synthetic-reviewer",
        "kind": "automated",
        "method": "Synthetic source check",
        "notes": "Attribution only; not clinical expertise.",
    }
    result = MechanicalReference.model_validate(reference_data | {"reviewers": [review]})
    assert isinstance(result.reviewers, tuple)
    assert result.reviewers[0].kind == "automated"
    with pytest.raises(ValidationError):
        ReviewerRecord.model_validate(review | {"trusted": True})
    with pytest.raises(ValidationError):
        ReviewerRecord.model_validate(review | {"kind": "expert"})


def test_group_and_source_id_do_not_accept_scalar_coercion(scope_data):
    with pytest.raises(ValidationError):
        ScopeGroup.model_validate({"container_source_path": "", "local_id": 0})
    scope_data["sources"][0]["source_id"] = False
    with pytest.raises(ValidationError):
        MechanicalScope.model_validate(scope_data)
