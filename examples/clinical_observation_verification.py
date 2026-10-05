"""Verify v2 source preservation with real retained bytes and production tools.

Operator-authored, no model, no gold, no quality score. This uses an existing
ClinicalTrials.gov/PubMed development package without network access. Every run
creates a new isolated SQLite Store and exports readable dossier artifacts; it
never opens the configured application database. Run from the repository:

    .venv/bin/python examples/clinical_observation_verification.py

Supply --package for the frozen package and --output-dir for a NEW output folder.
The package is local/ignored; no provider responses are embedded in this script.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.research.benchmark_bundle import load_blob, read_json
from researchdesk.research.benchmark_models import DatasetManifest
from researchdesk.research.models import SourceReference
from researchdesk.research.observation_models import ClinicalDossierV2
from researchdesk.research.quality import _pointer, _scalar_excerpt
from researchdesk.store import Store

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "artifacts/benchmark-development/clinical-development-v1/package"
LABEL = "Operator-authored direct-tool verification; no model, no gold, no quality score."
EXPECTED_MANIFEST_SHA256 = "2113168365543dc478d6490515b0d1deb668e9df1f4b50d59534f2eb7b1c5ba7"
EXPECTED_SOURCES = {
    "ctg-NCT03525444-current-20261005",
    "pubmed-31697873-efetch-20261005",
    "ctg-NCT05643742-current-20261005",
    "ctg-NCT00045968-current-20261005",
    "pubmed-29843811-efetch-20261005",
    "pubmed-36394838-efetch-20261005",
}


def present(value):
    return {"state": "present", "value": value}


def unresolved(reason="Not established within this deliberately bounded source extraction."):
    return {"state": "unresolved", "reason": reason}


def anchor(artifact, path):
    return {
        "artifact_id": artifact["id"],
        "artifact_sha256": artifact["sha256"],
        "source_path": path,
    }


def citation(artifact, path, excerpt=None):
    selected = _pointer(artifact["content"], path)
    if excerpt is None:
        excerpt = selected if isinstance(selected, str) else _scalar_excerpt(selected)
    if isinstance(selected, str):
        if excerpt not in selected:
            raise ValueError("Operator quotation does not occur in the retained source")
    elif excerpt != _scalar_excerpt(selected):
        raise ValueError("Operator scalar citation changed the retained value")
    return SourceReference(**anchor(artifact, path), excerpt=excerpt).model_dump(mode="json")


def abstract_citation(artifact, label, *, first_sentence=False):
    # Cite exact raw XML, not a re-serialized or decoded substitute. The production
    # evidence artifact retains XML as a string at /text.
    raw = artifact["content"]["text"]
    matches = re.findall(r"<AbstractText\b([^>]*)>(.*?)</AbstractText>", raw, re.DOTALL)
    bodies = [body for attrs, body in matches if f'Label="{label}"' in attrs]
    if len(bodies) != 1:
        raise ValueError(f"Expected exactly one retained abstract section: {label}")
    excerpt = bodies[0]
    if first_sentence:
        excerpt = excerpt.split(". ", 1)[0].rstrip(".") + "."
    return citation(artifact, "/text", excerpt)


def context(identifier, trial, artifact, path, kind, label):
    return {
        "context_id": identifier,
        "trial_id": trial,
        "source": anchor(artifact, path),
        "kind": kind,
        "label": label,
        "analysis_id": identifier,
    }


def count_observation(
    identifier,
    context_id,
    value,
    ref,
    *,
    refs=(),
    group=None,
    normalization="none",
    definition=None,
    stage=None,
    stages=None,
    assignment=None,
    status=None,
    endpoint=None,
    unit="participants",
):
    return {
        "kind": "population_count",
        "observation_id": identifier,
        "context_id": context_id,
        "source_refs": [ref, *refs],
        "group": group,
        "count": present(value),
        "count_normalization": normalization,
        "count_source_ref": ref,
        "unit": present(unit),
        "population_definition": present(definition) if definition else unresolved(),
        "reported_stage": present(stage) if stage else unresolved(),
        "stages": present(stages) if stages else unresolved(),
        "assignment_basis": present(assignment) if assignment else unresolved(),
        "reported_status": present(status) if status else unresolved(),
        "endpoint_observation_id": endpoint,
    }


def base_dossier(trial_id, family, intervention, indication, population):
    return {
        "schema_version": "clinical-dossier.v2",
        "intervention": intervention,
        "indication": indication,
        "population": population,
        "trials": [{"trial_id": trial_id, "trial_family_id": family}],
        "contexts": [],
        "observations": [],
        "reconciliations": [],
        "claims": [],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "No independent contrary-evidence search was performed. "
        "This is selected source-structure verification, not a comprehensive dossier.",
        "missing_inputs": [
            {
                "field": "prespecification and source history",
                "reason": "Historical registry versions and full protocol/SAP documents "
                "were not reviewed.",
                "consequence": "Prespecification and amendment chronology remain unresolved.",
            }
        ],
        "uncertainty": [
            LABEL,
            "This extraction-only output makes no clinical or investment conclusion.",
        ],
        "forecast": None,
    }


def vertex_dossier(sources):
    source = sources["ctg-NCT03525444-current-20261005"]
    publication = sources["pubmed-31697873-efetch-20261005"]
    trial = "NCT03525444"
    dossier = base_dossier(
        trial,
        "vertex-vx17-445-102",
        "Elexacaftor/tezacaftor/ivacaftor",
        "Cystic fibrosis",
        "Source-specific enrollment, dosing and analysis populations",
    )
    flow_path = "/record/resultsSection/participantFlowModule"
    recruitment = citation(source, flow_path + "/recruitmentDetails")
    dossier["contexts"] = [
        context(
            "vertex.registry",
            trial,
            source,
            "/record",
            "study_design",
            "Retained registry snapshot",
        ),
        context(
            "vertex.flow",
            trial,
            source,
            flow_path,
            "participant_flow",
            "Overall-study participant flow",
        ),
        context(
            "vertex.publication",
            trial,
            publication,
            "/text",
            "publication_analysis",
            "Published abstract population statement",
        ),
    ]
    enrollment_path = "/record/protocolSection/designModule/enrollmentInfo"
    dossier["observations"].append(
        count_observation(
            "vertex.enrolled",
            "vertex.registry",
            405,
            citation(source, enrollment_path + "/count"),
            refs=[citation(source, enrollment_path + "/type"), recruitment],
            definition="Participants enrolled in the registry study",
            stage="Enrollment",
            stages=["enrolled"],
            status="actual",
        )
    )
    publication_count = abstract_citation(publication, "RESULTS", first_sentence=True)
    dossier["observations"].append(
        count_observation(
            "vertex.randomized_and_dosed",
            "vertex.publication",
            403,
            publication_count,
            normalization="reported_in_text",
            definition="Participants who underwent randomization and received at least one dose",
            stage="Randomized and received at least one dose",
            stages=["randomized", "dosed"],
        )
    )
    flow = _pointer(source["content"], flow_path)
    for milestone_index, expected_counts, stage in (
        (0, [203, 200], "started"),
        (1, [201, 202], "safety_set"),
    ):
        milestone = flow["periods"][0]["milestones"][milestone_index]
        milestone_path = f"{flow_path}/periods/0/milestones/{milestone_index}"
        for index, achievement in enumerate(milestone["achievements"]):
            value = int(achievement["numSubjects"])
            if value != expected_counts[index]:
                raise ValueError(
                    "The fixed development source differs from the verified population example"
                )
            refs = [citation(source, milestone_path + "/type"), recruitment]
            if stage == "safety_set":
                refs.append(citation(source, milestone_path + "/comment"))
            dossier["observations"].append(
                count_observation(
                    f"vertex.{stage}.{achievement['groupId']}",
                    "vertex.flow",
                    value,
                    citation(source, milestone_path + f"/achievements/{index}/numSubjects"),
                    refs=refs,
                    group={
                        "container": anchor(source, flow_path),
                        "local_id": achievement["groupId"],
                    },
                    normalization="integer_from_digit_string",
                    definition=(
                        "Safety set grouped by actual treatment received"
                        if stage == "safety_set"
                        else "Participants starting the overall-study period in the reported group"
                    ),
                    stage=milestone["type"],
                    stages=[stage],
                    assignment="actual_treatment_received" if stage == "safety_set" else None,
                )
            )
    for outcome_index in (0, 9, 12):
        path = f"/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/{outcome_index}"
        outcome = _pointer(source["content"], path)
        cid, eid = f"vertex.outcome.{outcome_index}", f"vertex.endpoint.{outcome_index}"
        dossier["contexts"].append(
            context(cid, trial, source, path, "outcome_analysis", outcome["title"])
        )
        groups = [
            {"container": anchor(source, path), "local_id": g["id"]} for g in outcome["groups"]
        ]
        counts = []
        for index, raw in enumerate(outcome["denoms"][0]["counts"]):
            count_id = f"vertex.denominator.{outcome_index}.{raw['groupId']}"
            counts.append(count_id)
            dossier["observations"].append(
                count_observation(
                    count_id,
                    cid,
                    int(raw["value"]),
                    citation(source, path + f"/denoms/0/counts/{index}/value"),
                    refs=[
                        citation(source, path + "/populationDescription"),
                        citation(source, path + "/denoms/0/units"),
                    ],
                    group={"container": anchor(source, path), "local_id": raw["groupId"]},
                    normalization="integer_from_digit_string",
                    definition=outcome["populationDescription"],
                    stages=["analyzed"],
                    endpoint=eid,
                    unit=outcome["denoms"][0]["units"],
                )
            )
        refs = [
            citation(source, path + "/" + field)
            for field in ("title", "type", "timeFrame", "populationDescription")
        ]
        refs.extend(citation(source, path + f"/groups/{i}/title") for i in range(len(groups)))
        dossier["observations"].append(
            {
                "kind": "endpoint",
                "observation_id": eid,
                "context_id": cid,
                "source_refs": refs,
                "definition": present(outcome["title"]),
                "reported_role": present(outcome["type"].lower()),
                "timeframe": present(outcome["timeFrame"]),
                "time_origin": unresolved(),
                "population_definition": present(outcome["populationDescription"]),
                "comparator_description": unresolved(
                    "Group labels are retained; no comparison validity is inferred."
                ),
                "population_count_ids": counts,
                "groups": groups,
                "prespecification": unresolved(),
                "prespecification_refs": [],
            }
        )
    dossier["reconciliations"].append(
        {
            "observation_ids": ["vertex.enrolled", "vertex.randomized_and_dosed"],
            "relationship": "compatible_contexts",
            "kind": "fact",
            "source_refs": [recruitment],
            "explanation": "The registry explains that 405 enrolled, two were not dosed, "
            "and results concern 403 dosed participants. The publication's randomized-and-dosed "
            "population is retained without asserting total randomized enrollment.",
        }
    )
    dossier["claims"].append(
        {
            "id": "vertex.enrollment_explanation",
            "kind": "fact",
            "trial_ids": [trial],
            "statement": "The retained registry distinguishes enrolled from dosed participants.",
            "source_refs": [recruitment],
        }
    )
    return dossier


def dcvax_dossier(sources):
    source = sources["ctg-NCT00045968-current-20261005"]
    earlier = sources["pubmed-29843811-efetch-20261005"]
    later = sources["pubmed-36394838-efetch-20261005"]
    trial = "NCT00045968"
    dossier = base_dossier(
        trial,
        "northwest-dcvax-l-020221",
        "DCVax-L",
        "Glioblastoma",
        "Original assignment and later externally controlled analysis, separately reported",
    )
    dossier["contexts"] = [
        context(
            "dcvax.registry", trial, source, "/record", "study_design", "Retained current registry"
        ),
        context(
            "dcvax.original",
            trial,
            earlier,
            "/text",
            "publication_analysis",
            "Original allocation described by 2018 abstract",
        ),
        context(
            "dcvax.later_assignment",
            trial,
            later,
            "/text",
            "publication_analysis",
            "Original randomized allocation described within the later abstract",
        ),
        context(
            "dcvax.external",
            trial,
            later,
            "/text",
            "publication_analysis",
            "Externally controlled analysis described by later abstract",
        ),
    ]
    original = abstract_citation(earlier, "METHODS")
    later_assignment = abstract_citation(later, "RESULTS", first_sentence=True)
    external = abstract_citation(later, "DESIGN, SETTING, AND PARTICIPANTS")
    endpoint = abstract_citation(later, "MAIN OUTCOMES AND MEASURES")
    for identifier, cid, scope, allocation, comparator, refs in [
        (
            "dcvax.original_assignment",
            "dcvax.original",
            "trial_assignment",
            "randomized",
            "concurrent_internal",
            [original],
        ),
        (
            "dcvax.later_original_assignment",
            "dcvax.later_assignment",
            "trial_assignment",
            "randomized",
            "concurrent_internal",
            [later_assignment],
        ),
        (
            "dcvax.external_comparison",
            "dcvax.external",
            "analysis_comparison",
            "nonrandomized",
            "external",
            [external],
        ),
    ]:
        dossier["observations"].append(
            {
                "kind": "design",
                "observation_id": identifier,
                "context_id": cid,
                "source_refs": refs,
                "design_scope": scope,
                "study_type": unresolved(),
                "allocation": present(allocation),
                "intervention_model": unresolved(),
                "masking": unresolved(),
                "phase": unresolved(),
                "comparator_source": present(comparator),
            }
        )
    for identifier, cid, definition, refs in [
        ("dcvax.original_primary", "dcvax.original", "Progression-free survival", [original]),
        (
            "dcvax.later_primary",
            "dcvax.external",
            "Overall survival in newly diagnosed glioblastoma compared with external controls",
            [endpoint],
        ),
    ]:
        dossier["observations"].append(
            {
                "kind": "endpoint",
                "observation_id": identifier,
                "context_id": cid,
                "source_refs": refs,
                "definition": present(definition),
                "reported_role": present("primary"),
                "timeframe": unresolved(),
                "time_origin": unresolved(),
                "population_definition": unresolved(),
                "comparator_description": unresolved(),
                "population_count_ids": [],
                "groups": [],
                "prespecification": unresolved(
                    "Amendment timing and prespecification are not established by these sources."
                ),
                "prespecification_refs": [],
            }
        )
    dossier["observations"].append(
        {
            "kind": "availability",
            "observation_id": "dcvax.registry_results",
            "context_id": "dcvax.registry",
            "source_refs": [citation(source, "/record/hasResults")],
            "subject": "registry_results",
            "available": present(False),
            "available_source_ref": citation(source, "/record/hasResults"),
            "scope_description": "Posted results flag in this retained registry snapshot only; "
            "publications are separately present.",
        }
    )
    dossier["observations"].append(
        {
            "kind": "availability",
            "observation_id": "dcvax.results_section_key",
            "context_id": "dcvax.registry",
            "source_refs": [],
            "subject": "registry_results",
            "available": {
                "state": "source_absent",
                "reason": "The exact resultsSection key is absent from this retained registry "
                "record; this does not assert that trial results are absent elsewhere.",
                "proof": {"parent": anchor(source, "/record"), "key": "resultsSection"},
            },
            "available_source_ref": None,
            "scope_description": "Presence of the resultsSection JSON key within this single "
            "retained registry snapshot only.",
        }
    )
    dossier["reconciliations"] = [
        {
            "observation_ids": ["dcvax.original_assignment", "dcvax.external_comparison"],
            "relationship": "compatible_contexts",
            "kind": "inference",
            "source_refs": [original, external],
            "explanation": "Original assignment and the later external-comparator analysis "
            "are different contexts; both source descriptions are preserved.",
            "inference_basis": "The earlier abstract describes randomized allocation; the later "
            "abstract describes a nonrandomized external comparison. This does not establish "
            "causal validity.",
        },
        {
            "observation_ids": ["dcvax.later_original_assignment", "dcvax.external_comparison"],
            "relationship": "compatible_contexts",
            "kind": "inference",
            "source_refs": [later_assignment, external],
            "explanation": "The same later publication describes original randomized assignment "
            "and an externally controlled nonrandomized analysis as distinct contexts.",
            "inference_basis": "Its RESULTS sentence reports randomized trial groups; its DESIGN "
            "section describes the external comparison. Shared source provenance does not make "
            "assignment and analysis interchangeable or establish causal validity.",
        },
        {
            "observation_ids": ["dcvax.original_primary", "dcvax.later_primary"],
            "relationship": "unresolved_difference",
            "kind": "inference",
            "source_refs": [original, endpoint],
            "explanation": "The abstracts describe different primary endpoints. Amendment "
            "chronology and prespecification remain unresolved.",
            "inference_basis": "Different endpoint labels are retained; no historical protocol/SAP "
            "evidence is supplied to resolve timing or approvals.",
        },
    ]
    dossier["claims"] = [
        {
            "id": "dcvax.same_publication_contexts",
            "kind": "fact",
            "trial_ids": [trial],
            "statement": "The later abstract reports original randomized assignment in its "
            "RESULTS section and describes an externally controlled nonrandomized analysis "
            "in its DESIGN section.",
            "source_refs": [later_assignment, external],
        },
        {
            "id": "dcvax.contexts",
            "kind": "fact",
            "trial_ids": [trial],
            "statement": "The earlier abstract reports randomized allocation; the later abstract "
            "describes an externally controlled nonrandomized analysis.",
            "source_refs": [original, external],
        },
    ]
    return dossier


def load_package(package):
    manifest = DatasetManifest.model_validate(read_json(package / "dataset-manifest.json"))
    if manifest.sha256 != EXPECTED_MANIFEST_SHA256:
        raise ValueError("The source manifest differs from this example's pinned acquisition")
    if {source.source_id for source in manifest.sources} != EXPECTED_SOURCES:
        raise ValueError("This example requires the documented six-source development package")
    if any(
        case.reference_id is not None or case.reference_method != "unlabelled"
        for case in manifest.cases
    ):
        raise ValueError("This verification accepts only the unlabelled development package")
    contents = {
        source.source_id: load_blob(package / "blobs", source.artifact_sha256)
        for source in manifest.sources
    }
    return manifest, contents


def verify_preservation(saved):
    vertex = {item["observation_id"]: item for item in saved["vertex"]["observations"]}
    expected = {
        "vertex.enrolled": 405,
        "vertex.randomized_and_dosed": 403,
        "vertex.safety_set.FG000": 201,
        "vertex.safety_set.FG001": 202,
        "vertex.denominator.0.OG000": 203,
        "vertex.denominator.0.OG001": 200,
        "vertex.denominator.9.OG000": 74,
        "vertex.denominator.9.OG001": 71,
        "vertex.denominator.12.OG000": 200,
    }
    for identifier, value in expected.items():
        if vertex[identifier]["count"] != present(value):
            raise ValueError(f"Stored population changed: {identifier}")
    first, pk = (
        vertex[key]["group"]
        for key in ("vertex.denominator.0.OG000", "vertex.denominator.12.OG000")
    )
    if first["local_id"] != pk["local_id"] or first["container"] == pk["container"]:
        raise ValueError("Outcome-local group identities were collapsed")
    dcvax = {item["observation_id"]: item for item in saved["dcvax"]["observations"]}
    if (
        dcvax["dcvax.original_assignment"]["design_scope"] != "trial_assignment"
        or dcvax["dcvax.external_comparison"]["design_scope"] != "analysis_comparison"
    ):
        raise ValueError("Original assignment and later analysis were collapsed")
    assignment = dcvax["dcvax.later_original_assignment"]
    external = dcvax["dcvax.external_comparison"]
    contexts = {item["context_id"]: item for item in saved["dcvax"]["contexts"]}
    assignment_context = contexts[assignment["context_id"]]
    external_context = contexts[external["context_id"]]
    if (
        assignment["design_scope"] != "trial_assignment"
        or assignment["allocation"] != present("randomized")
        or assignment_context["context_id"] == external_context["context_id"]
        or assignment_context["analysis_id"] == external_context["analysis_id"]
        or assignment_context["source"] != external_context["source"]
    ):
        raise ValueError("Distinct contexts in the same later publication were collapsed")
    missing_section = dcvax["dcvax.results_section_key"]["available"]
    if (
        missing_section["state"] != "source_absent"
        or missing_section["proof"]["key"] != "resultsSection"
        or missing_section["proof"]["parent"] != contexts["dcvax.registry"]["source"]
        or dcvax["dcvax.registry_results"]["available"] != present(False)
    ):
        raise ValueError("Scoped key absence and the separate false flag were collapsed")
    if dcvax["dcvax.later_primary"]["prespecification"]["state"] != "unresolved":
        raise ValueError("Unresolved prespecification was replaced by an assertion")
    if any(dossier["forecast"] is not None for dossier in saved.values()):
        raise ValueError("Extraction-only verification must not manufacture a forecast")


def _call(store, registry, case_id, task_id, worker, name, arguments):
    call_id = str(uuid4())
    row = store.begin_tool_call(task_id, call_id, name, arguments, worker_id=worker)
    if row["status"] != "running":
        raise ValueError("Direct-tool admission was blocked")
    ctx = ToolContext(store, case_id, task_id, call_id, worker, lambda: store.is_cancelled(task_id))
    result = registry.execute(name, arguments, ctx)
    store.finish_tool_call(
        row["id"],
        "completed" if result["ok"] else "failed",
        result=result,
        error=result.get("error"),
        worker_id=worker,
    )
    if not result["ok"]:
        raise ValueError(f"Production tool failed: {result['error']['code']}")
    return result["data"]


def run_verification(package: Path, output_dir: Path):
    manifest, contents = load_package(package)
    output_dir.mkdir(parents=True, exist_ok=False)
    database_url = f"sqlite:///{(output_dir / 'verification.db').resolve()}"
    store = Store(database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        artifact_dir=output_dir,
        provider="disabled",
        retrieval_mode="lexical",
        read_only=False,
        openai_api_key="",
        alpaca_api_key="",
        alpaca_secret_key="",
        operator_token="",
    )
    report = {
        "mode": "operator_authored_direct_tools",
        "status": "running",
        "statement": LABEL,
        "model_calls": 0,
        "reference_labels_created": False,
        "quality_score": None,
        "dataset_manifest_sha256": manifest.sha256,
        "sources_imported": len(contents),
        "database_url": database_url,
        "dossiers": [],
    }
    saved, active_task = {}, None
    try:
        library = store.create_case("Frozen clinical evidence · direct verification", LABEL)
        artifacts = {}
        for record in manifest.sources:
            artifact = store.put_artifact(
                library["id"],
                None,
                "evidence",
                record.source_id,
                contents[record.source_id],
                {
                    "source_id": record.source_id,
                    "url": str(record.public_url),
                    "verification_mode": "direct_tools",
                },
            )
            if artifact["sha256"] != record.artifact_sha256:
                raise ValueError("Imported source content hash changed")
            artifacts[record.source_id] = artifact
        research = ResearchTools(store, settings)
        registry = research.registry()
        for family, builder in (("vertex", vertex_dossier), ("dcvax", dcvax_dossier)):
            dossier = ClinicalDossierV2.model_validate(builder(artifacts)).model_dump(mode="json")
            case = store.create_case(f"Operator-authored v2 verification · {family}", LABEL)
            task = store.create_task(case["id"], "researcher", LABEL)
            worker = "direct-verification-" + str(uuid4())
            if not store.claim_task(worker, task_id=task["id"]):
                raise ValueError("Could not claim the isolated verification task")
            active_task = (task["id"], worker)

            call = partial(_call, store, registry, case["id"], task["id"], worker)

            if family == "vertex":
                record = artifacts["ctg-NCT03525444-current-20261005"]
                stem = "/record/resultsSection/outcomeMeasuresModule/outcomeMeasures"
                pages = [
                    call("inspect_source", {"artifact_id": record["id"], "source_path": path})
                    for path in (
                        "/record/protocolSection/designModule/enrollmentInfo/count",
                        stem + "/0/denoms/0/counts/0/value",
                        stem + "/0/groups/0/title",
                        stem + "/12/groups/0/title",
                    )
                ]
                if (
                    pages[0].get("value") != 405
                    or pages[1].get("text") != "203"
                    or pages[1]["node_type"] != "string"
                ):
                    raise ValueError("Source navigation changed a raw count type/value")
                if pages[2]["text"] == pages[3]["text"]:
                    raise ValueError("Source navigation collapsed outcome group identities")
            receipt = call(
                "submit_clinical_dossier",
                {"title": f"Operator-authored verification · {family}", "dossier": dossier},
            )
            artifact = store.get_artifact(receipt["id"])
            validation = artifact["content"]["validation"]
            if artifact["content"]["dossier"] != dossier or not validation["valid"]:
                failed = [
                    item["code"] for item in validation.get("checks", []) if not item["passed"]
                ]
                raise ValueError(
                    "Stored dossier failed structure/attribution checks: "
                    + ",".join(sorted(set(failed)))
                )
            saved[family] = artifact["content"]["dossier"]
            path = output_dir / f"{family}-dossier-artifact.json"
            path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            )
            report["dossiers"].append(
                {
                    "family": family,
                    "case_id": case["id"],
                    "artifact_id": artifact["id"],
                    "artifact_sha256": artifact["sha256"],
                    "artifact_file": str(path.resolve()),
                    "structure_and_attribution_valid": validation["valid"],
                    "coverage": validation["coverage"],
                }
            )
            store.update_task(
                task["id"],
                worker_id=worker,
                status="completed",
                summary=LABEL,
                result={"artifact_ids": [artifact["id"]], "verification_mode": "direct_tools"},
            )
            active_task = None
        verify_preservation(saved)
        report["status"] = "passed"
        report["preservation_checks"] = [
            "separate_population_denominators",
            "outcome_local_group_identity",
            "assignment_vs_analysis_context",
            "same_source_multiple_contexts",
            "scoped_key_absence_vs_false_flag",
            "unresolved_prespecification",
            "no_forecast_or_scoring",
        ]
    except Exception as error:
        report.update(
            status="failed", error={"type": type(error).__name__, "message": str(error)[:1500]}
        )
        if active_task:
            store.update_task(
                active_task[0],
                worker_id=active_task[1],
                status="failed",
                error={"code": "DIRECT_VERIFICATION_FAILED", "message": str(error)[:1500]},
            )
        raise
    finally:
        store.close()
        report_path = output_dir / "verification-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.output_dir or ROOT / "artifacts" / (
        "clinical-observation-verification-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:6]
    )
    try:
        report = run_verification(args.package.resolve(), output.resolve())
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "statement": LABEL,
                    "error": {"type": type(error).__name__, "message": str(error)[:1500]},
                },
                ensure_ascii=True,
                allow_nan=False,
            )
        )
        return 1
    encoded = json.dumps(report, ensure_ascii=True, allow_nan=False)
    if len(encoded) > 12_000:
        raise RuntimeError(
            "Verification summary exceeded its output bound; inspect the report file"
        )
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
