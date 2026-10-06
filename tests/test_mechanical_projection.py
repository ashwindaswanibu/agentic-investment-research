"""A copying baseline cannot depend on private reference labels or a model."""

from copy import deepcopy

import pytest
from test_scoped_quality import fixture as fixture_data

from researchdesk.research.mechanical_projection import (
    ProjectionInputError,
    project_mechanical_dossier,
)
from researchdesk.research.quality import validate_dossier
from researchdesk.research.scoped_quality import score_mechanical_dossier
from researchdesk.store import content_hash

scoped_fixture = fixture_data


def project(data):
    return project_mechanical_dossier(data[1], data[3])


def get_observation(dossier, identifier):
    return next(item for item in dossier.observations if item.observation_id == identifier)


def rebind_source(data):
    source = data[3]["stable-source"]
    source["sha256"] = content_hash(source["content"])
    data[1]["sources"][0]["artifact_sha256"] = source["sha256"]


def test_projection_uses_only_public_inputs_and_has_no_clinical_claims(scoped_fixture):
    output = project(scoped_fixture)
    assert output.claims == []
    assert output.reconciliations == []
    assert output.forecast is None
    assert get_observation(output, "count0").count.value == 7
    assert get_observation(output, "available").available.value is False
    assert get_observation(output, "null").available.value is None
    assert get_observation(output, "absent").available.state == "source_absent"
    assert get_observation(output, "endpoint").population_count_ids == ["count0"]
    assert get_observation(output, "endpoint").prespecification.state == "unresolved"
    source = scoped_fixture[3]["stable-source"]
    assert validate_dossier(output, {source["id"]: source}).valid
    # The private key is consulted only by this separate test assertion.
    result = score_mechanical_dossier(output, *scoped_fixture[1:])
    assert result["matched_fields"] == result["expected_fields"] == 11
    assert result["candidate_validation"]["schema_valid"]
    scoped_fixture[2].clear()
    scoped_fixture[2]["not_a_reference"] = True
    assert project(scoped_fixture) == output


@pytest.mark.parametrize("raw", [True, "12", 12.0, -1, {}, []])
def test_inexpressible_count_is_unresolved_not_coerced(scoped_fixture, raw):
    scoped_fixture[3]["stable-source"]["content"]["record"]["enrollment"]["count"] = raw
    rebind_source(scoped_fixture)
    output = project(scoped_fixture)
    observation = get_observation(output, "enrollment")
    assert observation.count.state == "unresolved"
    assert observation.count_source_ref is None
    assert observation.count_normalization == "none"
    assert get_observation(output, "available").available.state == "present"


@pytest.mark.parametrize("raw", ["007", "+7", "7.0", " 7", "٧", "7e0", "1" * 21])
def test_digit_string_normalization_does_not_guess(scoped_fixture, raw):
    source = scoped_fixture[3]["stable-source"]
    source["content"]["record"]["outcomes"][0]["denoms"][0]["counts"][0]["value"] = raw
    rebind_source(scoped_fixture)
    assert get_observation(project(scoped_fixture), "count0").count.state == "unresolved"


def test_public_enum_lookup_is_exact_and_not_blanket_case_folding(scoped_fixture):
    field = next(
        f for f in scoped_fixture[1]["fields"] if f["field_id"] == "enrollment.reported_status"
    )
    field.update(
        normalization="enum_lookup",
        enum_map=[
            {"source_token": "ACTUAL", "value": "actual"},
            {"source_token": "ESTIMATED", "value": "estimated"},
        ],
    )
    assert get_observation(project(scoped_fixture), "enrollment").reported_status.value == "actual"
    scoped_fixture[3]["stable-source"]["content"]["record"]["enrollment"]["status"] = "Actual"
    rebind_source(scoped_fixture)
    assert (
        get_observation(project(scoped_fixture), "enrollment").reported_status.state == "unresolved"
    )


def test_wrong_group_does_not_copy_a_plausible_count(scoped_fixture):
    source = scoped_fixture[3]["stable-source"]
    source["content"]["record"]["outcomes"][0]["denoms"][0]["counts"][0]["groupId"] = "other"
    rebind_source(scoped_fixture)
    assert get_observation(project(scoped_fixture), "count0").count.state == "unresolved"


def test_missing_parent_is_unresolved_but_exact_missing_key_has_proof(scoped_fixture):
    source = scoped_fixture[3]["stable-source"]
    del source["content"]["record"]["enrollment"]
    rebind_source(scoped_fixture)
    output = project(scoped_fixture)
    assert get_observation(output, "enrollment").count.state == "unresolved"
    source["content"]["record"]["enrollment"] = {}
    rebind_source(scoped_fixture)
    field = get_observation(project(scoped_fixture), "enrollment").count
    assert field.state == "source_absent"
    assert field.proof.parent.source_path == "/record/enrollment"
    assert field.proof.key == "count"


@pytest.mark.parametrize("change", ["hash", "kind", "missing", "duplicate_group", "oversize"])
def test_input_integrity_and_resource_failures_do_not_become_extractions(scoped_fixture, change):
    source = scoped_fixture[3]["stable-source"]
    if change == "hash":
        source["content"]["tamper"] = True
    elif change == "kind":
        source["kind"] = "evaluation_reference"
    elif change == "missing":
        scoped_fixture[3].clear()
    elif change == "duplicate_group":
        groups = source["content"]["record"]["outcomes"][0]["groups"]
        groups.append(deepcopy(groups[0]))
        rebind_source(scoped_fixture)
    else:
        source["content"]["large"] = "x" * 2_000_001
        rebind_source(scoped_fixture)
    with pytest.raises(ProjectionInputError):
        project(scoped_fixture)
