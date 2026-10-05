"""Adversarial source-boundary fixtures only; no clinical entailment or quality score."""

import json
from copy import deepcopy

import pytest
from test_observation_models import anchor as anchor_fixture
from test_observation_models import availability as availability_fixture
from test_observation_models import count as count_fixture
from test_observation_models import design as design_fixture
from test_observation_models import dossier_v2 as dossier_fixture
from test_observation_models import endpoint as endpoint_fixture
from test_observation_models import ref as ref_fixture

from researchdesk.research import observation_quality as validation
from researchdesk.research import quality
from researchdesk.research.observation_models import ClinicalDossierV2
from researchdesk.store import content_hash

anchor = anchor_fixture
availability = availability_fixture
count = count_fixture
design = design_fixture
dossier_v2 = dossier_fixture
endpoint = endpoint_fixture
ref = ref_fixture


def bind_versions(value, sources):
    if isinstance(value, dict):
        if "artifact_id" in value and value["artifact_id"] in sources:
            value["artifact_sha256"] = sources[value["artifact_id"]]["sha256"]
        for item in value.values():
            bind_versions(item, sources)
    elif isinstance(value, list):
        for item in value:
            bind_versions(item, sources)


def refresh(dossier, sources):
    for artifact in sources.values():
        artifact["sha256"] = content_hash(artifact["content"])
    bind_versions(dossier, sources)


def failures(dossier, sources):
    return {
        item.code
        for item in validation.validate_observation_dossier(dossier, sources).checks
        if not item.passed
    }


@pytest.fixture
def grounded(dossier_v2):  # noqa: F811
    content = {
        "record": {
            "text": "Synthetic test statement.",
            "count": 12,
            "groups": [{"id": "GROUP0", "title": "Fictional treatment A"}],
            "hasResults": False,
            "explicitNull": None,
            "emptyObject": {},
            "array": [],
        },
        "record_extra": {"text": "Synthetic test statement."},
        "elsewhere": {"text": "Synthetic test statement."},
    }
    sources = {
        "synthetic-evidence": {
            "id": "synthetic-evidence",
            "kind": "evidence",
            "content": content,
        }
    }
    # JSON round-trip removes fixture aliases: changing one citation must not
    # accidentally change every observation that reused the same fixture dict.
    dossier = json.loads(json.dumps(dossier_v2))
    dossier["observations"][1]["endpoint_observation_id"] = "synthetic.endpoint"
    dossier["observations"][2]["groups"] = [deepcopy(dossier["observations"][1]["group"])]
    dossier["observations"][3]["source_refs"][0].update(
        source_path="/record/hasResults", excerpt="false"
    )
    dossier["observations"][3]["available_source_ref"] = deepcopy(
        dossier["observations"][3]["source_refs"][0]
    )
    refresh(dossier, sources)
    return dossier, sources


def test_complete_grounded_fixture_passes_with_explicit_semantic_limits(grounded):
    dossier, sources = grounded
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    assert report.coverage.observations == 4
    assert report.coverage.contexts == 1
    assert report.coverage.fully_attributed_observations == 4
    assert report.coverage.distinct_sources == 1
    assert any("not claim truth" in text for text in report.limitations)
    assert any("No clinical reference score" in text for text in report.limitations)


@pytest.mark.parametrize("outside", ["/record_extra/text", "/elsewhere/text", None])
def test_quote_presence_does_not_override_exact_context_subtree(grounded, outside):
    dossier, sources = grounded
    dossier["observations"][0]["source_refs"][0]["source_path"] = outside
    assert "observation_source_context" in failures(dossier, sources)


def test_valid_other_source_version_cannot_be_substituted_within_context(grounded):
    dossier, sources = grounded
    other = deepcopy(sources["synthetic-evidence"])
    other["id"] = "same-trial-new-snapshot"
    other["content"]["revision"] = "new source version"
    other["sha256"] = content_hash(other["content"])
    sources[other["id"]] = other
    citation = dossier["observations"][0]["source_refs"][0]
    citation.update(artifact_id=other["id"], artifact_sha256=other["sha256"])
    failed = failures(dossier, sources)
    assert "observation_source_context" in failed
    assert "source_version_match" not in failed  # Citation itself is a real newer version.


@pytest.mark.parametrize(
    "collection,code",
    [
        ("trials", "unique_trial_ids"),
        ("contexts", "unique_context_ids"),
        ("observations", "unique_observation_ids"),
        ("claims", "unique_claim_ids"),
    ],
)
def test_duplicate_record_ids_are_rejected(grounded, collection, code):
    dossier, sources = grounded
    dossier[collection].append(deepcopy(dossier[collection][0]))
    assert code in failures(dossier, sources)


@pytest.mark.parametrize("field", ["observation_context", "context_trial", "claim_trial"])
def test_unknown_context_or_trial_reference_is_not_a_valid_observation(grounded, field):
    dossier, sources = grounded
    if field == "observation_context":
        dossier["observations"][0]["context_id"] = "missing"
        expected = "context_reference_exists"
    elif field == "context_trial":
        dossier["contexts"][0]["trial_id"] = "missing"
        expected = "trial_reference_exists"
    else:
        dossier["claims"][0]["trial_ids"] = ["missing"]
        expected = "trial_reference_exists"
    assert expected in failures(dossier, sources)


def outcomes_fixture(grounded):
    dossier, sources = grounded
    original = deepcopy(sources["synthetic-evidence"]["content"]["record"])
    different = deepcopy(original)
    different["count"] = 7
    different["groups"][0]["title"] = "Different fictional treatment B"
    sources["synthetic-evidence"]["content"]["outcomes"] = [original, different]
    contexts, observations = [], []
    for index in range(2):
        context = deepcopy(dossier["contexts"][0])
        context.update(context_id=f"outcome-{index}", kind="outcome_analysis")
        context["source"]["source_path"] = f"/outcomes/{index}"
        contexts.append(context)
        count, endpoint = deepcopy(dossier["observations"][1:3])
        for item in (count, endpoint):
            item["context_id"] = context["context_id"]
            item["observation_id"] += f".{index}"
            item["source_refs"][0]["source_path"] = f"/outcomes/{index}/text"
        count["count"]["value"] = 12 if index == 0 else 7
        count["count_source_ref"].update(
            source_path=f"/outcomes/{index}/count", excerpt=str(count["count"]["value"])
        )
        count["group"]["container"]["source_path"] = f"/outcomes/{index}"
        count["endpoint_observation_id"] = endpoint["observation_id"]
        endpoint["population_count_ids"] = [count["observation_id"]]
        endpoint["groups"] = [deepcopy(count["group"])]
        observations += [count, endpoint]
    dossier["contexts"], dossier["observations"] = contexts, observations
    refresh(dossier, sources)
    return dossier, sources


def test_same_local_group_id_in_distinct_outcomes_is_preserved_without_merging(grounded):
    dossier, sources = outcomes_fixture(grounded)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    parsed = ClinicalDossierV2.model_validate(dossier)
    first, second = parsed.observations[0], parsed.observations[2]
    assert first.group.local_id == second.group.local_id == "GROUP0"
    assert first.group.key != second.group.key
    assert (first.count.value, second.count.value) == (12, 7)


def test_broad_context_cannot_hide_swapped_owning_group_container(grounded):
    dossier, sources = outcomes_fixture(grounded)
    dossier["contexts"][0]["source"]["source_path"] = ""
    dossier["observations"][0]["group"]["container"]["source_path"] = "/outcomes/1"
    assert not validation.validate_observation_dossier(dossier, sources).valid


@pytest.mark.parametrize(
    "bad_groups", [[], [{"id": "OTHER"}], [{"id": "GROUP0"}, {"id": "GROUP0"}]]
)
def test_local_group_id_must_occur_exactly_once_in_owning_container(grounded, bad_groups):
    dossier, sources = grounded
    sources["synthetic-evidence"]["content"]["record"]["groups"] = bad_groups
    refresh(dossier, sources)
    assert "group_local_identity" in failures(dossier, sources)


@pytest.mark.parametrize(
    "parent,key,valid",
    [
        ("/record", "missingKey", True),
        ("/record", "explicitNull", False),
        ("/record", "hasResults", False),
        ("/record/missingParent", "anything", False),
        ("/record/explicitNull", "anything", False),
        ("/record/array", "anything", False),
        ("/record/count", "anything", False),
        ("/record/emptyObject", "", True),
    ],
)
def test_missing_key_proof_requires_existing_object_and_actual_absence(
    grounded, parent, key, valid
):
    dossier, sources = grounded
    dossier["observations"][0]["masking"] = {
        "state": "source_absent",
        "reason": "Only literal key absence is asserted.",
        "proof": {
            "parent": {**dossier["contexts"][0]["source"], "source_path": parent},
            "key": key,
        },
    }
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid is valid, report.failed_checks
    if not valid:
        assert "source_key_absent" in {c.code for c in report.failed_checks}


def test_missing_key_in_other_subtree_cannot_prove_current_context_absence(grounded):
    dossier, sources = grounded
    dossier["observations"][0]["masking"] = {
        "state": "source_absent",
        "reason": "Deliberately wrong parent context.",
        "proof": {
            "parent": {**dossier["contexts"][0]["source"], "source_path": "/elsewhere"},
            "key": "masking",
        },
    }
    assert "observation_source_context" in failures(dossier, sources)


def test_endpoint_must_list_count_that_claims_it_as_owner(grounded):
    dossier, sources = grounded
    dossier["observations"][2]["population_count_ids"] = []
    assert not validation.validate_observation_dossier(dossier, sources).valid


@pytest.mark.parametrize("target", [None, "synthetic.assignment", "missing-observation"])
def test_endpoint_count_list_requires_reciprocal_correct_endpoint(grounded, target):
    dossier, sources = grounded
    dossier["observations"][1]["endpoint_observation_id"] = target
    assert not validation.validate_observation_dossier(dossier, sources).valid


def test_endpoint_denominator_cannot_cross_analysis_contexts(grounded):
    dossier, sources = outcomes_fixture(grounded)
    dossier["observations"][0]["endpoint_observation_id"] = dossier["observations"][3][
        "observation_id"
    ]
    assert "population_endpoint_context" in failures(dossier, sources)


@pytest.mark.parametrize(
    "corruption", ["content", "stored_hash", "citation_hash", "kind", "identity"]
)
def test_source_integrity_identity_and_evidence_kind_are_all_required(grounded, corruption):
    dossier, sources = grounded
    artifact = sources["synthetic-evidence"]
    if corruption == "content":
        artifact["content"]["unrelated_field"] = "Even an unquoted content change matters"
    elif corruption == "stored_hash":
        artifact["sha256"] = "0" * 64
    elif corruption == "citation_hash":
        dossier["observations"][0]["source_refs"][0]["artifact_sha256"] = "0" * 64
    elif corruption == "kind":
        artifact["kind"] = "note"
    else:
        artifact["id"] = "different-source"
    assert not validation.validate_observation_dossier(dossier, sources).valid


@pytest.mark.parametrize(
    "raw,excerpt,valid",
    [
        (False, "false", True),
        (False, "False", False),
        (None, "null", True),
        (0, "0", True),
        (12.0, "12", False),
        (12.0, "12.0", True),
        ({"nested": "false"}, "false", False),
        (["false"], "false", False),
    ],
)
def test_raw_scalar_citations_preserve_exact_json_type_and_entire_value(
    grounded, raw, excerpt, valid
):
    dossier, sources = grounded
    sources["synthetic-evidence"]["content"]["record"]["rawScalar"] = raw
    dossier["claims"][0]["source_refs"][0].update(source_path="/record/rawScalar", excerpt=excerpt)
    refresh(dossier, sources)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid is valid, report.failed_checks


@pytest.mark.parametrize(
    "raw,value,normalization,valid",
    [
        (12, 12, "none", True),
        (0, 0, "none", True),
        (None, None, "none", True),
        (12, 13, "none", False),
        (12.0, 12, "none", False),
        (True, 1, "none", False),
        ("12", 12, "none", False),
        (12, None, "none", False),
        (None, 0, "none", False),
        ("12", 12, "integer_from_digit_string", True),
        ("0", 0, "integer_from_digit_string", True),
        ("12", 13, "integer_from_digit_string", False),
        ("012", 12, "integer_from_digit_string", False),
        (" 12 ", 12, "integer_from_digit_string", False),
        ("+12", 12, "integer_from_digit_string", False),
        ("12.0", 12, "integer_from_digit_string", False),
        ("１２", 12, "integer_from_digit_string", False),
        (12, 12, "integer_from_digit_string", False),
        ("The source reports 12 fictional participants.", 12, "reported_in_text", True),
        (12, 12, "reported_in_text", False),
    ],
)
def test_explicit_count_normalization_matches_source_representation(
    grounded, raw, value, normalization, valid
):
    dossier, sources = grounded
    sources["synthetic-evidence"]["content"]["record"]["count"] = raw
    observation = dossier["observations"][1]
    observation["count"] = {"state": "present", "value": value}
    observation["count_normalization"] = normalization
    # Text quotes remain text; scalars use the complete canonical JSON lexeme.
    observation["count_source_ref"]["excerpt"] = (
        raw
        if isinstance(raw, str)
        else ("null" if raw is None else "true" if raw is True else str(raw))
    )
    refresh(dossier, sources)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid is valid, report.failed_checks
    if not valid:
        assert "count_value_matches_source" in {c.code for c in report.failed_checks}


def test_text_count_normalization_does_not_claim_semantic_entailment(grounded):
    dossier, sources = grounded
    raw = "Synthetic text containing a count of 12 and an unrelated interval of 24 weeks."
    sources["synthetic-evidence"]["content"]["record"]["count"] = raw
    observation = dossier["observations"][1]
    observation["count_source_ref"]["excerpt"] = raw
    observation["count_normalization"] = "reported_in_text"
    refresh(dossier, sources)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    assert any("interprets its source correctly" in text for text in report.limitations)


class ReadCounter(dict):
    def __init__(self, content):
        super().__init__(content)
        self.reads = 0

    def get(self, *args, **kwargs):
        self.reads += 1
        return super().get(*args, **kwargs)


def test_dossier_global_byte_budget_stops_before_any_source_read(grounded):
    dossier, sources = grounded
    dossier["uncertainty"] = ["Synthetic filler " + "x" * 11_500 for _ in range(18)]
    counted = ReadCounter(sources)
    report = validation.validate_observation_dossier(dossier, counted)
    assert not report.valid and report.checks[0].code == "dossier_budget"
    assert counted.reads == 0


def add_anchor_only_sources(dossier, sources, number, padding=0):
    for index in range(number):
        identifier = f"anchor-only-{index}"
        artifact = deepcopy(sources["synthetic-evidence"])
        artifact["id"] = identifier
        artifact["content"]["padding"] = "x" * padding
        artifact["sha256"] = content_hash(artifact["content"])
        sources[identifier] = artifact
        context = deepcopy(dossier["contexts"][0])
        context["context_id"] = f"anchor-only-context-{index}"
        context["source"].update(artifact_id=identifier, artifact_sha256=artifact["sha256"])
        dossier["contexts"].append(context)


def test_global_source_limit_counts_anchors_not_just_quotations(grounded):
    dossier, sources = grounded
    add_anchor_only_sources(dossier, sources, 30)
    counted = ReadCounter(sources)
    report = validation.validate_observation_dossier(dossier, counted)
    assert not report.valid and report.checks[0].code == "dossier_budget"
    assert counted.reads == 0


def test_thirty_distinct_sources_are_admitted_without_merging_duplicate_content(grounded):
    dossier, sources = grounded
    add_anchor_only_sources(dossier, sources, 29)
    parsed = ClinicalDossierV2.model_validate(dossier)
    assert len(validation.check_observation_budget(parsed)) == 30
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks


def test_total_source_bytes_include_anchor_only_sources_before_hashing(grounded, monkeypatch):
    dossier, sources = grounded
    add_anchor_only_sources(dossier, sources, 6, padding=1_400_000)

    def no_hash(_):
        raise AssertionError("Expensive source hashes must follow admission")

    monkeypatch.setattr(quality, "_hash", no_hash)
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid and report.checks[0].code == "source_budget"


def test_repeated_anchor_and_quote_references_hash_each_source_once(grounded, monkeypatch):
    dossier, sources = grounded
    actual_hash = quality._hash
    calls = []

    def counted(content):
        calls.append(content)
        return actual_hash(content)

    monkeypatch.setattr(quality, "_hash", counted)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    assert len(calls) == 1


def test_prespecification_can_cite_separate_exact_protocol_source(grounded):
    dossier, sources = grounded
    protocol = {
        "id": "synthetic-protocol",
        "kind": "evidence",
        "content": {"text": "Synthetic protocol prospectively names the endpoint."},
    }
    protocol["sha256"] = content_hash(protocol["content"])
    sources[protocol["id"]] = protocol
    endpoint = dossier["observations"][2]
    endpoint["prespecification"] = {"state": "present", "value": "yes"}
    endpoint["prespecification_refs"] = [
        {
            "artifact_id": protocol["id"],
            "artifact_sha256": protocol["sha256"],
            "source_path": "/text",
            "excerpt": protocol["content"]["text"],
        }
    ]
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    endpoint["prespecification_refs"][0]["artifact_sha256"] = "0" * 64
    assert "source_version_match" in failures(dossier, sources)


def test_extraction_only_dossier_allows_explicit_null_forecast(grounded):
    dossier, sources = grounded
    dossier["forecast"] = None
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
    assert not any(check.code.startswith("forecast_") for check in report.checks)


@pytest.mark.parametrize("forecast", [{}, {"status": "abstain"}, {"status": "unknown"}, "none"])
def test_null_forecast_does_not_admit_malformed_forecasts(grounded, forecast):
    dossier, sources = grounded
    dossier["forecast"] = forecast
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert any(check.code.startswith("schema.") for check in report.failed_checks)


def test_invalid_context_citation_is_excluded_from_attribution_coverage(grounded):
    dossier, sources = grounded
    dossier["observations"][0]["source_refs"][0]["source_path"] = "/elsewhere/text"
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert report.coverage.fully_attributed_observations == 3


def test_failed_count_representation_is_excluded_from_attribution_coverage(grounded):
    dossier, sources = grounded
    dossier["observations"][1]["count"]["value"] = 13
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert report.coverage.fully_attributed_observations == 3


def test_failed_missing_key_proof_is_excluded_from_attribution_coverage(grounded):
    dossier, sources = grounded
    dossier["observations"][0]["masking"] = {
        "state": "source_absent",
        "reason": "Deliberately claims an existing null-valued key is absent.",
        "proof": {"parent": deepcopy(dossier["contexts"][0]["source"]), "key": "explicitNull"},
    }
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert report.coverage.fully_attributed_observations == 3


@pytest.mark.parametrize(
    "raw,value,excerpt,valid",
    [
        (False, False, "false", True),
        (True, True, "true", True),
        (None, None, "null", True),
        (True, False, "true", False),
        (False, True, "false", False),
        (None, False, "null", False),
        (False, None, "false", False),
        (0, False, "0", False),
        (1, True, "1", False),
        ("false", False, "false", False),
        ("No results posted.", False, "No results posted.", False),
    ],
)
def test_availability_preserves_exact_boolean_or_null_without_coercion(
    grounded, raw, value, excerpt, valid
):
    dossier, sources = grounded
    sources["synthetic-evidence"]["content"]["record"]["hasResults"] = raw
    observation = dossier["observations"][3]
    observation["available"] = {"state": "present", "value": value}
    observation["source_refs"][0]["excerpt"] = excerpt
    observation["available_source_ref"]["excerpt"] = excerpt
    refresh(dossier, sources)
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid is valid, report.failed_checks
    if not valid:
        assert "available_value_matches_source" in {c.code for c in report.failed_checks}
        assert report.coverage.fully_attributed_observations == 3


def test_present_availability_cannot_omit_its_exact_value_binding(grounded):
    dossier, sources = grounded
    del dossier["observations"][3]["available_source_ref"]
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert any(c.code.startswith("schema.") for c in report.failed_checks)


def test_unresolved_availability_cannot_smuggle_a_value_citation(grounded):
    dossier, sources = grounded
    dossier["observations"][3]["available"] = {
        "state": "unresolved",
        "reason": "Only narrative evidence is available.",
    }
    report = validation.validate_observation_dossier(dossier, sources)
    assert not report.valid
    assert any(c.code.startswith("schema.") for c in report.failed_checks)
    del dossier["observations"][3]["available_source_ref"]
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks


def test_escaped_and_whitespace_json_pointer_keys_keep_exact_context_identity(grounded):
    dossier, sources = grounded
    record = sources["synthetic-evidence"]["content"]["record"]
    record[" a/b~c "] = deepcopy(record)
    escaped = "/record/ a~1b~0c "

    def relocate(value):
        if isinstance(value, dict):
            path = value.get("source_path")
            if isinstance(path, str) and (path == "/record" or path.startswith("/record/")):
                value["source_path"] = escaped + path[len("/record") :]
            for item in value.values():
                relocate(item)
        elif isinstance(value, list):
            for item in value:
                relocate(item)

    relocate(dossier)
    refresh(dossier, sources)
    parsed = ClinicalDossierV2.model_validate(dossier)
    assert parsed.contexts[0].source.source_path == escaped
    report = validation.validate_observation_dossier(parsed, sources)
    assert report.valid, report.failed_checks


def test_missing_key_spelling_preserves_whitespace(grounded):
    dossier, sources = grounded
    sources["synthetic-evidence"]["content"]["record"][" key "] = None
    field = {
        "state": "source_absent",
        "reason": "Literal exact-key comparison only.",
        "proof": {"parent": deepcopy(dossier["contexts"][0]["source"]), "key": " key "},
    }
    dossier["observations"][0]["masking"] = field
    refresh(dossier, sources)
    assert "source_key_absent" in failures(dossier, sources)
    field["proof"]["key"] = "key"
    report = validation.validate_observation_dossier(dossier, sources)
    assert report.valid, report.failed_checks
