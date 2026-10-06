"""Build a private mechanical reference package from pinned registry source bytes.

This is an automated, partially scoped source projection, not expert gold or a
model evaluation. It never reads candidate dossiers, invokes a model, accesses
the network, or opens an application Store. The original package is unchanged.

Run from the repository:
    .venv/bin/python examples/build_mechanical_reference_package.py

The public scopes contain questions and stable source identities only. The
private references and projection ledgers contain expected values and must never
be imported as candidate evidence. Every output file is private by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from researchdesk.research.benchmark_bundle import canonical_bytes, load_blob, read_json
from researchdesk.research.benchmark_models import DatasetManifest
from researchdesk.research.quality import _pointer
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.research.scoped_quality import validate_mechanical_reference
from researchdesk.store import content_hash

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "artifacts/benchmark-development/clinical-development-v1/package"
PINNED_MANIFEST_SHA256 = "2113168365543dc478d6490515b0d1deb668e9df1f4b50d59534f2eb7b1c5ba7"
SOURCE_IDS = {
    "ctg-NCT03525444-current-20261005",
    "pubmed-31697873-efetch-20261005",
    "ctg-NCT05643742-current-20261005",
    "ctg-NCT00045968-current-20261005",
    "pubmed-29843811-efetch-20261005",
    "pubmed-36394838-efetch-20261005",
}
CASE_PLANS = (
    ("development-vertex-vx445", "NCT03525444", "ctg-NCT03525444-current-20261005", (0,)),
    ("development-crispr-ctx112", "NCT05643742", "ctg-NCT05643742-current-20261005", (0, 1)),
    ("development-northwest-dcvax-l", "NCT00045968", "ctg-NCT00045968-current-20261005", (0,)),
)
VERSION = "2026-10-05.mechanical.v2"
AUTHORING = {
    "kind": "automated",
    "method": "direct_registry_field_projection",
    "prior_source_familiarity": True,
    "blind_reference_authoring": False,
    "candidate_outputs_read": False,
    "expert_adjudication": False,
    "review_status": "unreviewed",
}
LIMITATIONS = (
    "Automated direct-registry source projection for explicit partial mechanical scope only; "
    "not independently adjudicated expert gold or a clinical research quality measure.",
    "The implementation author had prior source familiarity and contributed to a separate "
    "verification example. This builder does not read that example or any candidate outputs; "
    "reference authoring is not blind and reviewers are initially empty.",
    "Public pointers and identity mappings make this guided extraction, not source discovery. "
    "All expected values, rationale and absence states remain private.",
    "No PubMed prose interpretation, prespecification, reconciliation entailment, efficacy, "
    "historical availability or investment judgment is scored.",
    "These are three development families, not held-out evidence of general model quality. "
    "Exact source agreement does not establish clinical truth.",
)


def load_sources(package: Path, *, expected_manifest_sha256=PINNED_MANIFEST_SHA256):
    """Read and integrity-check all sources before producing any output.

    The hash override exists for explicit synthetic unit fixtures; the CLI always
    uses the original pinned manifest. No caller-supplied candidate data is used.
    """
    manifest = DatasetManifest.model_validate(read_json(package / "dataset-manifest.json"))
    if manifest.sha256 != expected_manifest_sha256:
        raise ValueError("Source manifest does not match the pinned acquisition")
    if {source.source_id for source in manifest.sources} != SOURCE_IDS:
        raise ValueError("Expected exactly the documented six-source development package")
    if {case.case_id for case in manifest.cases} != {plan[0] for plan in CASE_PLANS}:
        raise ValueError("The package case identities differ from this explicit scope")
    if any(
        case.reference_method != "unlabelled"
        or case.reference_id is not None
        or case.split != "development"
        or case.scope != "extraction_only"
        for case in manifest.cases
    ):
        raise ValueError("The input must be unlabelled, extraction-only development evidence")
    contents = {
        source.source_id: load_blob(package / "blobs", source.artifact_sha256)
        for source in manifest.sources
    }
    return manifest, contents


class CaseProjection:
    """Separate public questions and identities from private derived values."""

    def __init__(self, case, trial, source, contents, source_records):
        self.case, self.trial, self.source = case, trial, source
        self.content = contents[source]
        self.source_records = source_records
        self.contexts, self.observations, self.fields, self.references = [], [], [], []

    def context(self, path, kind):
        value = _pointer(self.content, path)
        if type(value) is not dict:
            raise ValueError(f"Context must select an object: {path}")
        identifier = f"{self.case.case_id}.c{len(self.contexts) + 1:02d}"
        self.contexts.append(
            {
                "context_id": identifier,
                "trial_id": self.trial,
                "trial_family_id": self.case.trial_family_ids[0],
                "source_id": self.source,
                "source_path": path,
                "kind": kind,
                "analysis_id": identifier,
            }
        )
        return identifier

    def observation(self, context_id, kind, group=None, endpoint_observation_id=None):
        identifier = f"{self.case.case_id}.o{len(self.observations) + 1:02d}"
        self.observations.append(
            {
                "observation_id": identifier,
                "context_id": context_id,
                "kind": kind,
                "group": group,
                "endpoint_observation_id": endpoint_observation_id,
            }
        )
        return identifier

    def field(
        self,
        observation_id,
        name,
        path,
        *,
        raw_type,
        normalization="identity",
        allowed_tokens=None,
        group_path=None,
        severity="ordinary",
    ):
        value = _pointer(self.content, path)
        if type(value) is not raw_type:
            raise ValueError(f"Unexpected raw type for {path}: expected {raw_type.__name__}")
        if raw_type is int and value < 0:
            raise ValueError(f"Negative count at {path}")
        if raw_type is str and not value:
            raise ValueError(f"Empty selected source string at {path}")
        if normalization == "canonical_digit_string":
            if re.fullmatch(r"0|[1-9][0-9]*", value) is None or len(value) > 20:
                raise ValueError(f"Expected bounded canonical ASCII digit-string count at {path}")
            expected = int(value)
        elif normalization == "enum_lookup":
            if not allowed_tokens or value not in allowed_tokens:
                raise ValueError(f"Unexpected source enum token at {path}")
            expected = value.lower()
        elif normalization == "identity":
            expected = value
        else:
            raise ValueError("Undeclared normalization")
        identifier = f"{observation_id}.{name}"
        question = f"Extract the source-specific {name} from the exact field {path}."
        if normalization == "canonical_digit_string":
            question += (
                " Preserve the raw citation; convert canonical ASCII decimal digits "
                "(0 or a nonzero leading digit, at most 20 digits) to integer."
            )
        elif normalization == "enum_lookup":
            question += (
                " Use only the exact source-token to value mapping in enum_map, "
                "retaining the original source citation. Unknown tokens remain unresolved."
            )
        else:
            question += " Preserve the exact scalar value and source type."
        self.fields.append(
            {
                "field_id": identifier,
                "observation_id": observation_id,
                "field_name": name,
                "source_path": path,
                "question": question,
                "severity": severity,
                "normalization": normalization,
                **(
                    {
                        "enum_map": [
                            {"source_token": token, "value": token.lower()}
                            for token in sorted(allowed_tokens)
                        ]
                    }
                    if normalization == "enum_lookup"
                    else {}
                ),
            }
        )
        self.references.append(
            {
                "field_id": identifier,
                "expected_state": "present",
                "expected_value": expected,
                "source_id": self.source,
                "source_path": path,
                "normalization": normalization,
                "source_group_path": group_path,
                "rationale": "Derived directly from this exact retained registry scalar under "
                "the declared deterministic normalization; no clinical interpretation.",
            }
        )

    def absent_key(self, observation_id, parent, key):
        value = _pointer(self.content, parent)
        if type(value) is not dict or key in value:
            raise ValueError("Missing-key projection requires an existing object without that key")
        identifier = f"{observation_id}.available"
        self.fields.append(
            {
                "field_id": identifier,
                "observation_id": observation_id,
                "field_name": "available",
                "source_path": parent + "/" + key.replace("~", "~0").replace("/", "~1"),
                "question": f"Inspect the object at {parent} for the exact key {key}. Preserve "
                "the field-state distinction and provide parent/key proof for an absence claim; "
                "a failed lookup is not proof.",
                "severity": "data_integrity",
                "normalization": "identity",
            }
        )
        self.references.append(
            {
                "field_id": identifier,
                "expected_state": "source_absent",
                "source_id": self.source,
                "source_path": parent,
                "normalization": "identity",
                "missing_key": key,
                "rationale": "The retained parent is an object and exact key nonmembership "
                "was checked. This does not assert absence of results elsewhere.",
            }
        )

    def endpoint(self, path, *, posted=False):
        context_id = self.context(path, "outcome_analysis" if posted else "study_design")
        observation_id = self.observation(context_id, "endpoint")
        self.field(
            observation_id, "definition", path + ("/title" if posted else "/measure"), raw_type=str
        )
        self.field(observation_id, "timeframe", path + "/timeFrame", raw_type=str)
        if posted:
            self.field(
                observation_id,
                "reported_role",
                path + "/type",
                raw_type=str,
                normalization="enum_lookup",
                allowed_tokens={"PRIMARY", "SECONDARY"},
            )
        return context_id, observation_id

    def posted_counts(self, path):
        context_id, endpoint_id = self.endpoint(path, posted=True)
        outcome = _pointer(self.content, path)
        groups, denoms = outcome.get("groups"), outcome.get("denoms")
        if type(groups) is not list or type(denoms) is not list or len(denoms) != 1:
            raise ValueError("Selected outcome requires groups and exactly one denominator entry")
        group_ids = []
        for group in groups:
            if type(group) is not dict or type(group.get("id")) is not str:
                raise ValueError("Group descriptors require exact string IDs")
            if type(group.get("title")) is not str or not group["title"]:
                raise ValueError("Group descriptors require a nonempty source title")
            group_ids.append(group["id"])
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("Ambiguous repeated group ID inside one outcome")
        counts = denoms[0].get("counts") if type(denoms[0]) is dict else None
        if type(counts) is not list or not counts:
            raise ValueError("Denominator counts must be a nonempty array")
        seen = set()
        for index, item in enumerate(counts):
            if type(item) is not dict or type(item.get("groupId")) is not str:
                raise ValueError("A denominator entry must contain a string groupId")
            local_id = item["groupId"]
            if local_id not in group_ids or local_id in seen:
                raise ValueError("Denominator must map once to a unique group in its own outcome")
            seen.add(local_id)
            observation_id = self.observation(
                context_id,
                "population_count",
                {"container_source_path": path, "local_id": local_id},
                endpoint_observation_id=endpoint_id,
            )
            stem = path + f"/denoms/0/counts/{index}"
            self.field(
                observation_id,
                "count",
                stem + "/value",
                raw_type=str,
                normalization="canonical_digit_string",
                group_path=stem + "/groupId",
                severity="data_integrity",
            )
            self.field(observation_id, "unit", path + "/denoms/0/units", raw_type=str)

    def finish(self):
        scope = MechanicalScope.model_validate(
            {
                "scope_id": self.case.case_id + ".mechanical-scope",
                "version": VERSION,
                "case_id": self.case.case_id,
                "sources": [
                    {
                        "source_id": source_id,
                        "artifact_sha256": self.source_records[source_id].artifact_sha256,
                    }
                    for source_id in self.case.source_ids
                ],
                "contexts": self.contexts,
                "observations": self.observations,
                "fields": self.fields,
            }
        )
        reference = MechanicalReference.model_validate(
            {
                "reference_id": self.case.case_id + ".mechanical-reference",
                "scope_sha256": scope.sha256,
                "fields": self.references,
                "limitations": LIMITATIONS,
                "reviewers": [],
            }
        )
        return scope, reference


def derive_references(manifest, contents):
    """Project only the predeclared registry paths, never prose or candidate outputs."""
    cases = {case.case_id: case for case in manifest.cases}
    sources = {source.source_id: source for source in manifest.sources}
    result = []
    for case_id, trial, source, endpoint_indexes in CASE_PLANS:
        case = cases[case_id]
        if source not in case.source_ids or len(case.trial_family_ids) != 1:
            raise ValueError("Registry must belong to the declared single-family case")
        p = CaseProjection(case, trial, source, contents, sources)
        enrollment = "/record/protocolSection/designModule/enrollmentInfo"
        context_id = p.context(enrollment, "study_design")
        observation_id = p.observation(context_id, "population_count")
        p.field(
            observation_id, "count", enrollment + "/count", raw_type=int, severity="data_integrity"
        )
        p.field(
            observation_id,
            "reported_status",
            enrollment + "/type",
            raw_type=str,
            normalization="enum_lookup",
            allowed_tokens={"ACTUAL", "ESTIMATED"},
        )
        for index in endpoint_indexes:
            p.endpoint(f"/record/protocolSection/outcomesModule/primaryOutcomes/{index}")
        if trial == "NCT03525444":
            for index in (0, 9, 12):
                p.posted_counts(
                    f"/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/{index}"
                )
        context_id = p.context("/record", "other")
        observation_id = p.observation(context_id, "availability")
        p.field(
            observation_id,
            "available",
            "/record/hasResults",
            raw_type=bool,
            severity="data_integrity",
        )
        if trial != "NCT03525444":
            observation_id = p.observation(context_id, "availability")
            p.absent_key(observation_id, "/record", "resultsSection")
        result.append((case, source, *p.finish()))
    if sum(len(scope.observations) for _, _, scope, _ in result) != 20:
        raise ValueError("The predeclared 20-observation scope changed")
    return result


def _write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def build_package(
    package: Path,
    output: Path,
    *,
    expected_manifest_sha256=PINNED_MANIFEST_SHA256,
    created_at=None,
):
    """Validate inputs first, then publish a new private directory atomically."""
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output exists; choose a new package version")
    if any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Output paths cannot traverse symlinks")
    if output.resolve().is_relative_to(package.resolve()):
        raise ValueError("Output must be outside the retained source package")
    manifest, contents = load_sources(package, expected_manifest_sha256=expected_manifest_sha256)
    projections = derive_references(manifest, contents)
    source_records = {source.source_id: source for source in manifest.sources}
    for case, _, scope, reference in projections:
        validate_mechanical_reference(
            scope,
            reference,
            {
                source_id: {
                    "id": source_records[source_id].artifact_id,
                    "kind": "evidence",
                    "sha256": source_records[source_id].artifact_sha256,
                    "content": contents[source_id],
                }
                for source_id in case.source_ids
            },
        )
    now = created_at or datetime.now(UTC)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    now = now.astimezone(UTC)
    if now < manifest.created_at:
        raise ValueError("Reference creation cannot precede source-package creation")
    records = {source.source_id: source for source in manifest.sources}
    files, blobs, case_entries = {}, {}, []
    for source in manifest.sources:
        blobs[source.artifact_sha256] = contents[source.source_id]
    for case, registry_id, scope, reference in projections:
        scope_json, reference_json = (
            scope.model_dump(mode="json"),
            reference.model_dump(mode="json"),
        )
        scope_file = f"public/scopes/{case.case_id}.json"
        reference_file = f"private/references/{case.case_id}.json"
        files[scope_file], files[reference_file] = scope_json, reference_json
        blobs[scope.sha256], blobs[reference.sha256] = scope_json, reference_json
        reference_fields = {
            field.field_id: field.model_dump(mode="json") for field in reference.fields
        }
        ledger = {
            "schema_version": "clinical-mechanical-projection.v1",
            "kind": "programmatic_reference",
            "case_id": case.case_id,
            "scope_sha256": scope.sha256,
            "reference_sha256": reference.sha256,
            "method": reference.method,
            "authoring": AUTHORING,
            "public_source_bindings": scope_json["sources"],
            "context_bindings": scope_json["contexts"],
            "observation_bindings": scope_json["observations"],
            "field_ledger": [
                {
                    "scope": field.model_dump(mode="json"),
                    "reference": reference_fields[field.field_id],
                }
                for field in scope.fields
            ],
            "limitations": list(LIMITATIONS),
            "reviewers": [],
        }
        projection_hash = content_hash(ledger)
        blobs[projection_hash] = ledger
        projection_source = {
            "source_id": case.case_id + ".programmatic-projection",
            "version": VERSION,
            "kind": "programmatic_reference",
            "artifact_id": "sha256:" + projection_hash,
            "artifact_sha256": projection_hash,
            "upstream_source_id": registry_id,
            "upstream_public_url": str(records[registry_id].public_url),
            "created_at": now.isoformat(),
        }
        case_entries.append(
            {
                "case_id": case.case_id,
                "trial_family_ids": list(case.trial_family_ids),
                "source_ids": list(case.source_ids),
                "sources": scope_json["sources"],
                "scope_file": scope_file,
                "scope_sha256": scope.sha256,
                "reference_file": reference_file,
                "reference_id": reference.reference_id,
                "reference_sha256": reference.sha256,
                "reference_method": "programmatic",
                "reference_source_ids": [projection_source["source_id"]],
                "projection_source": projection_source,
                "observations": len(scope.observations),
                "fields": len(scope.fields),
            }
        )
    index = {
        "schema_version": "clinical-mechanical-reference-package.v1",
        "created_at": now.isoformat(),
        "source_manifest_sha256": manifest.sha256,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "authoring": AUTHORING,
        "limitations": list(LIMITATIONS),
        "sources": [source.model_dump(mode="json") for source in manifest.sources],
        "cases": case_entries,
        "blob_sha256": sorted(blobs),
        "projection_url_policy": "upstream_public_url identifies the original public evidence. "
        "No public URL or hosting is asserted for private generated reference blobs.",
        "model_calls": 0,
        "quality_score": None,
        "protocol_created": False,
    }
    index = {**index, "sha256": content_hash(index)}
    files.update({f"blobs/{digest}.json": value for digest, value in blobs.items()})
    files["package-index.json"] = index
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".mechanical-reference-", dir=output.parent))
    try:
        for relative, value in files.items():
            _write_private(temporary / relative, value)
        if output.exists() or output.is_symlink():
            raise FileExistsError("Output appeared during generation; refusing overwrite")
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or ROOT / "artifacts" / (
        "mechanical-reference-package-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:6]
    )
    try:
        index = build_package(args.package.absolute(), output)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": str(error)[:1000],
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "created_unreviewed",
                "output": str(output.absolute()),
                "package_sha256": index["sha256"],
                "observations": sum(case["observations"] for case in index["cases"]),
                "fields": sum(case["fields"] for case in index["cases"]),
                "model_calls": 0,
                "quality_score": None,
                "expert_gold": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
