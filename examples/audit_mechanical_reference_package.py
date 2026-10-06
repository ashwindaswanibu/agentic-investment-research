"""Independently audit the bounded v2 registry reference package using only stdlib.

This checks retained source facts and public bindings, not candidate answers,
clinical truth, or provider behavior. It never imports ResearchDesk extraction
code. Run with --package DIRECTORY --output NEW_RECEIPT.json. Source packages
are read-only; an unsuccessful check never produces a success receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

MAX_BYTES = 2_000_000
MAX_BLOBS = 30
CASE_TRIALS = {
    "development-vertex-vx445": "NCT03525444",
    "development-crispr-ctx112": "NCT05643742",
    "development-northwest-dcvax-l": "NCT00045968",
}
ENUM_MAPS = {
    "reported_status": {"ACTUAL": "actual", "ESTIMATED": "estimated"},
    "reported_role": {"PRIMARY": "primary", "SECONDARY": "secondary"},
}
PUBLICATION_IDS = {
    "pubmed-31697873-efetch-20261005",
    "pubmed-29843811-efetch-20261005",
    "pubmed-36394838-efetch-20261005",
}


class AuditError(ValueError):
    """A bounded structural or source-fact check failed."""


def require(condition, code):
    if not condition:
        raise AuditError(code)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    path = path.absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_input")
    require(path.is_file(), "missing_input_file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input_too_large")
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical(value)  # Reject NaN, infinity and overflowed numeric literals.
    require(type(value) is dict, "json_root_not_object")
    return value


def local_file(package, relative):
    require(type(relative) is str, "invalid_package_path")
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "invalid_package_path")
    return package / path


def keyed(items, key):
    require(type(items) is list and bool(items), "empty_or_invalid_collection")
    result = {}
    for item in items:
        require(type(item) is dict, "invalid_collection_item")
        identifier = item.get(key)
        require(type(identifier) is str and bool(identifier), "invalid_identity")
        require(identifier not in result, "duplicate_identity")
        result[identifier] = item
    return result


def pointer(value, path):
    require(type(path) is str and path.startswith("/"), "invalid_pointer")
    for raw in path[1:].split("/"):
        require(re.search(r"~(?![01])", raw) is None, "invalid_pointer_escape")
        token = raw.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            require(re.fullmatch(r"0|[1-9][0-9]*", token) is not None, "invalid_array_index")
            require(int(token) < len(value), "missing_array_entry")
            value = value[int(token)]
        else:
            require(type(value) is dict and token in value, "missing_pointer_target")
            value = value[token]
    return value


def exact(left, right):
    return type(left) is type(right) and left == right


def normalize(raw, field):
    name, operation = field["field_name"], field["normalization"]
    if operation == "enum_lookup":
        require(name in ENUM_MAPS, "unsupported_enum_field")
        mapping = keyed(field.get("enum_map"), "source_token")
        require(
            {key: item.get("value") for key, item in mapping.items()} == ENUM_MAPS[name],
            "incorrect_public_enum_map",
        )
        require(type(raw) is str and raw in mapping, "unknown_source_enum")
        return mapping[raw]["value"]
    require("enum_map" not in field, "unexpected_enum_map")
    if operation == "canonical_digit_string":
        require(
            name == "count"
            and type(raw) is str
            and re.fullmatch(r"0|[1-9][0-9]*", raw) is not None
            and len(raw) <= 20,
            "invalid_canonical_count",
        )
        return int(raw)
    require(operation == "identity", "unsupported_normalization")
    require(raw is None or type(raw) in (str, int, bool), "non_scalar_source")
    return raw


def check_field_location(field, observation, context):
    """Interpret the narrow source-field contract independently of the builder."""
    name, path = field["field_name"], field["source_path"]
    base, kind = context["source_path"], observation["kind"]
    if kind == "availability":
        require(base == "/record" and context["kind"] == "other", "availability_context")
        require(
            name == "available" and path in ("/record/hasResults", "/record/resultsSection"),
            "availability_field",
        )
    elif kind == "endpoint":
        posted = re.fullmatch(
            r"/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/(0|9|12)", base
        )
        protocol = re.fullmatch(
            r"/record/protocolSection/outcomesModule/primaryOutcomes/[01]", base
        )
        require(bool(posted or protocol), "endpoint_context")
        require(
            context["kind"] == ("outcome_analysis" if posted else "study_design"),
            "endpoint_context_kind",
        )
        suffixes = {"definition": "title" if posted else "measure", "timeframe": "timeFrame"}
        if posted:
            suffixes["reported_role"] = "type"
        require(name in suffixes and path == base + "/" + suffixes[name], "endpoint_field")
    elif kind == "population_count":
        if observation.get("group") is None:
            require(
                base == "/record/protocolSection/designModule/enrollmentInfo"
                and context["kind"] == "study_design",
                "enrollment_context",
            )
            suffixes = {"count": "count", "reported_status": "type"}
            require(name in suffixes and path == base + "/" + suffixes[name], "enrollment_field")
        else:
            require(context["kind"] == "outcome_analysis", "denominator_context_kind")
            if name == "count":
                require(
                    re.fullmatch(re.escape(base) + r"/denoms/0/counts/[01]/value", path)
                    is not None,
                    "denominator_count_field",
                )
            else:
                require(
                    name == "unit" and path == base + "/denoms/0/units", "denominator_unit_field"
                )
    else:
        raise AuditError("unsupported_observation_kind")
    required = (
        "enum_lookup"
        if name in ENUM_MAPS
        else (
            "canonical_digit_string" if name == "count" and observation.get("group") else "identity"
        )
    )
    require(field["normalization"] == required, "field_normalization_contract")


def check_case(case, scope, reference, sources, blobs):
    case_id = case["case_id"]
    require(scope["case_id"] == case_id, "scope_case_identity")
    require(scope["schema_version"] == "clinical-mechanical-scope.v1", "scope_schema")
    require(scope["version"] == "2026-10-05.mechanical.v2", "unsupported_scope_version")
    require(reference["schema_version"] == "clinical-mechanical-reference.v1", "reference_schema")
    require(reference["reference_id"] == case["reference_id"], "reference_identity")
    require(reference["scope_sha256"] == digest(scope), "reference_scope_hash")
    require(reference["method"] == "programmatic_source_projection", "reference_method")
    scope_sources = keyed(scope["sources"], "source_id")
    require(set(scope_sources) == set(case["source_ids"]), "case_source_set")
    require(case["sources"] == scope["sources"], "case_source_bindings")
    for source_id, binding in scope_sources.items():
        require(
            source_id in sources
            and binding["artifact_sha256"] == sources[source_id]["artifact_sha256"],
            "scope_source_hash",
        )
    contexts = keyed(scope["contexts"], "context_id")
    observations = keyed(scope["observations"], "observation_id")
    fields = keyed(scope["fields"], "field_id")
    rules = keyed(reference["fields"], "field_id")
    require(set(fields) == set(rules), "reference_field_set")
    require(
        len(fields) == case["fields"] and len(observations) == case["observations"], "case_counts"
    )
    enrollment = "/record/protocolSection/designModule/enrollmentInfo"
    expected_paths = [enrollment + "/count", enrollment + "/type", "/record/hasResults"]
    expected_contexts = {enrollment, "/record"}
    primary_count = 2 if CASE_TRIALS[case_id] == "NCT05643742" else 1
    for position in range(primary_count):
        base = f"/record/protocolSection/outcomesModule/primaryOutcomes/{position}"
        expected_contexts.add(base)
        expected_paths.extend([base + "/measure", base + "/timeFrame"])
    if CASE_TRIALS[case_id] == "NCT03525444":
        for position, count in ((0, 2), (9, 2), (12, 1)):
            base = f"/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/{position}"
            expected_contexts.add(base)
            expected_paths.extend(base + suffix for suffix in ("/title", "/timeFrame", "/type"))
            for group_index in range(count):
                expected_paths.extend(
                    [base + f"/denoms/0/counts/{group_index}/value", base + "/denoms/0/units"]
                )
        expected_observations = 11
    else:
        expected_paths.append("/record/resultsSection")
        expected_observations = 5 if primary_count == 2 else 4
    require(
        Counter(f["source_path"] for f in fields.values()) == Counter(expected_paths),
        "bounded_field_inventory",
    )
    require(
        len(contexts) == len(expected_contexts)
        and {c["source_path"] for c in contexts.values()} == expected_contexts,
        "bounded_context_inventory",
    )
    require(len(observations) == expected_observations, "bounded_observation_inventory")
    require(
        type(case["trial_family_ids"]) is list and len(case["trial_family_ids"]) == 1,
        "bounded_trial_family",
    )
    require(
        len({(f["observation_id"], f["field_name"]) for f in fields.values()}) == len(fields),
        "duplicate_field_target",
    )
    for context in contexts.values():
        source_id = context["source_id"]
        require(source_id in scope_sources, "context_source_identity")
        source = blobs[sources[source_id]["artifact_sha256"]]
        require(type(pointer(source, context["source_path"])) is dict, "context_not_object")
        trial = pointer(source, "/record/protocolSection/identificationModule/nctId")
        require(trial == context["trial_id"] == CASE_TRIALS[case_id], "trial_identity")
        require(source_id == "ctg-" + trial + "-current-20261005", "registry_source_identity")
        require(context["trial_family_id"] in case["trial_family_ids"], "trial_family_identity")
        require(context.get("analysis_id") == context["context_id"], "analysis_identity")
    group_count = 0
    for observation in observations.values():
        require(observation["context_id"] in contexts, "observation_context_identity")
        require(observation.get("design_scope") is None, "unexpected_design_scope")
        context = contexts[observation["context_id"]]
        group = observation.get("group")
        if group is None:
            require(observation.get("endpoint_observation_id") is None, "unexpected_endpoint_link")
            continue
        group_count += 1
        require(observation["kind"] == "population_count", "group_observation_kind")
        require(group["container_source_path"] == context["source_path"], "group_container")
        source = blobs[sources[context["source_id"]]["artifact_sha256"]]
        outcome = pointer(source, group["container_source_path"])
        descriptors = keyed(outcome["groups"], "id")
        require(group["local_id"] in descriptors, "group_local_identity")
        require(
            all(type(g.get("title")) is str and bool(g["title"]) for g in descriptors.values()),
            "group_descriptor_title",
        )
        require(
            type(outcome["denoms"]) is list and len(outcome["denoms"]) == 1, "denominator_container"
        )
        counts = keyed(outcome["denoms"][0]["counts"], "groupId")
        require(
            set(counts) <= set(descriptors) and group["local_id"] in counts, "denominator_group"
        )
        endpoint_id = observation.get("endpoint_observation_id")
        require(endpoint_id in observations, "missing_endpoint_link")
        endpoint = observations[endpoint_id]
        require(
            endpoint["kind"] == "endpoint" and endpoint["context_id"] == observation["context_id"],
            "endpoint_binding",
        )
    states = {"present": 0, "source_absent": 0}
    for field_id, field in fields.items():
        rule = rules[field_id]
        require(field["observation_id"] in observations, "field_observation_identity")
        observation = observations[field["observation_id"]]
        context = contexts[observation["context_id"]]
        check_field_location(field, observation, context)
        require(rule["source_id"] == context["source_id"], "field_source_identity")
        require(rule["normalization"] == field["normalization"], "private_normalization")
        source = blobs[sources[rule["source_id"]]["artifact_sha256"]]
        state = rule["expected_state"]
        require(state in states, "unsupported_expected_state")
        states[state] += 1
        if state == "source_absent":
            require(
                field["field_name"] == "available"
                and field["source_path"] == "/record/resultsSection",
                "unexpected_absence_target",
            )
            require(
                rule["source_path"] == "/record" and rule["missing_key"] == "resultsSection",
                "absence_parent_key",
            )
            parent = pointer(source, rule["source_path"])
            require(
                type(parent) is dict and rule["missing_key"] not in parent, "absence_not_proven"
            )
            require(
                "expected_value" not in rule and rule.get("source_group_path") is None,
                "absence_scalar_or_group",
            )
            continue
        require(rule["source_path"] == field["source_path"], "field_source_pointer")
        raw = pointer(source, field["source_path"])
        value = normalize(raw, field)
        name = field["field_name"]
        require(exact(value, rule["expected_value"]), "reference_value_mismatch")
        if name == "count":
            require(type(value) is int and value >= 0, "count_type")
        elif name == "available":
            require(type(raw) is bool, "availability_type")
        else:
            require(type(value) is str and bool(value), "text_field_type")
        group = observation.get("group")
        if group and name == "count":
            group_path = field["source_path"].rsplit("/", 1)[0] + "/groupId"
            require(rule.get("source_group_path") == group_path, "count_group_pointer")
            require(pointer(source, group_path) == group["local_id"], "count_group_binding")
        else:
            require(rule.get("source_group_path") is None, "unexpected_group_pointer")
    require(
        {f["observation_id"] for f in fields.values()} == set(observations), "unscoped_observation"
    )
    require({o["context_id"] for o in observations.values()} == set(contexts), "unused_context")
    projection = case["projection_source"]
    ledger = blobs[projection["artifact_sha256"]]
    require(
        ledger["scope_sha256"] == digest(scope) and ledger["reference_sha256"] == digest(reference),
        "ledger_artifact_hashes",
    )
    require(
        ledger["case_id"] == case_id
        and ledger["public_source_bindings"] == scope["sources"]
        and ledger["context_bindings"] == scope["contexts"]
        and ledger["observation_bindings"] == scope["observations"],
        "ledger_bindings",
    )
    require(
        ledger["field_ledger"]
        == [{"scope": f, "reference": rules[f["field_id"]]} for f in scope["fields"]],
        "ledger_fields",
    )
    return {
        "case_id": case_id,
        "scope_sha256": digest(scope),
        "reference_sha256": digest(reference),
        "projection_sha256": projection["artifact_sha256"],
        "contexts": len(contexts),
        "observations": len(observations),
        "fields": len(fields),
        "group_endpoint_bindings": group_count,
        "field_states": states,
    }


def audit_package(package):
    """Return a digest-bound receipt only after every bounded check succeeds."""
    package = Path(package).absolute()
    index = read_json(package / "package-index.json")
    require(index["schema_version"] == "clinical-mechanical-reference-package.v1", "package_schema")
    require(
        digest({k: v for k, v in index.items() if k != "sha256"}) == index["sha256"],
        "package_index_hash",
    )
    digests = index["blob_sha256"]
    require(
        type(digests) is list
        and 0 < len(digests) <= MAX_BLOBS
        and len(set(digests)) == len(digests),
        "blob_inventory",
    )
    blobs = {}
    for sha in digests:
        require(type(sha) is str and re.fullmatch(r"[0-9a-f]{64}", sha), "invalid_blob_digest")
        blobs[sha] = read_json(package / "blobs" / (sha + ".json"))
        require(digest(blobs[sha]) == sha, "blob_content_hash")
    sources = keyed(index["sources"], "source_id")
    require(
        set(sources)
        == PUBLICATION_IDS
        | {"ctg-" + trial + "-current-20261005" for trial in CASE_TRIALS.values()},
        "bounded_source_set",
    )
    for source in sources.values():
        require(
            source["kind"] == "evidence" and source["artifact_sha256"] in blobs,
            "source_blob_binding",
        )
        require(
            source["artifact_id"] == "sha256:" + source["artifact_sha256"],
            "source_artifact_identity",
        )
    cases = keyed(index["cases"], "case_id")
    require(set(cases) == set(CASE_TRIALS), "bounded_case_set")
    receipts, used = [], {s["artifact_sha256"] for s in sources.values()}
    require(set(sources) == {s for c in cases.values() for s in c["source_ids"]}, "unused_source")
    for case in cases.values():
        scope = read_json(local_file(package, case["scope_file"]))
        reference = read_json(local_file(package, case["reference_file"]))
        for data, key in ((scope, "scope_sha256"), (reference, "reference_sha256")):
            sha = case[key]
            require(
                digest(data) == sha and sha in blobs and blobs[sha] == data, "artifact_copy_hash"
            )
            used.add(sha)
        used.add(case["projection_source"]["artifact_sha256"])
        receipts.append(check_case(case, scope, reference, sources, blobs))
    require(used == set(blobs), "unexpected_blob_inventory")
    return {
        "schema_version": "clinical-mechanical-independent-audit.v1",
        "status": "verified",
        "audited_at": datetime.now(UTC).isoformat(),
        "package_sha256": index["sha256"],
        "source_manifest_sha256": index["source_manifest_sha256"],
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reviewer": {
            "id": "researchdesk-independent-source-review",
            "kind": "independent_automated",
            "method": "stdlib_retained_source_and_public_contract_check",
            "project_extraction_code_imported": False,
            "candidate_outputs_read": False,
            "prior_source_exposure": True,
            "blind": False,
            "expert_adjudication": False,
        },
        "sources": [
            {"source_id": s["source_id"], "artifact_sha256": s["artifact_sha256"]}
            for s in sources.values()
        ],
        "cases": receipts,
        "counts": {
            "sources": len(sources),
            "blobs": len(blobs),
            **{
                key: sum(c[key] for c in receipts)
                for key in ("contexts", "observations", "fields", "group_endpoint_bindings")
            },
        },
        "limitations": [
            "Checks bounded v2 registry source agreement, not clinical truth.",
            "Checks publication integrity; does not adjudicate publication prose.",
            "Hashes bind supplied artifacts, not authenticity or historical availability.",
            "No model, security, integration, reconciliation or investment approval.",
            "Records the source-manifest digest without rederiving absent manifest bytes.",
        ],
    }


def write_receipt(output, receipt):
    """Publish exclusively; remove incomplete output on a write failure."""
    output = Path(output).absolute()
    require(not any(p.is_symlink() for p in (output, *output.parents)), "symlink_output")
    data = canonical(receipt)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(
            not args.output.resolve().is_relative_to(args.package.resolve()),
            "receipt_inside_source_package",
        )
        receipt = audit_package(args.package)
        write_receipt(args.output, receipt)
    except Exception as error:
        # Never echo source values or file contents through exception text.
        code = str(error) if isinstance(error, AuditError) else type(error).__name__
        print(json.dumps({"status": "failed", "error": code[:160]}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "verified",
                "package_sha256": receipt["package_sha256"],
                "fields": receipt["counts"]["fields"],
                "receipt": str(args.output.absolute()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
