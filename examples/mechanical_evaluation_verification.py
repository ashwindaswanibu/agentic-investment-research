"""Exercise a deterministic baseline and deliberate error on retained sources.

No model, trading, network or main application database is involved. A deliberately
incorrect copy is a test probe, not a competing research system. The private
reference is passed only to the operator evaluation after both outputs are frozen.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from researchdesk.mechanical_workflow import evaluate_mechanical_comparison
from researchdesk.research.benchmark_bundle import canonical_bytes, load_blob, read_json
from researchdesk.research.mechanical_projection import project_mechanical_dossier
from researchdesk.research.quality import validate_dossier
from researchdesk.research.scoped_models import MechanicalScope
from researchdesk.store import Store, content_hash


def verify(package: Path, output: Path):
    index = read_json(package / "package-index.json")
    if index.get("schema_version") != "clinical-mechanical-reference-package.v1" or (
        index.get("sha256") != content_hash({k: v for k, v in index.items() if k != "sha256"})
    ):
        raise ValueError("Invalid reference-package binding")
    if output.exists():
        raise ValueError("Choose a new output directory; prior verification remains immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mechanical-verification-", dir=output.parent))
    store = Store(f"sqlite:///{staging.absolute() / 'verification.sqlite'}")
    results = []
    try:
        for item in index["cases"]:
            scope = MechanicalScope.model_validate(
                load_blob(package / "blobs", item["scope_sha256"])
            )
            case = store.create_case(
                f"Verification only · {scope.case_id}"[:200],
                "Deterministic source copying versus a deliberately incorrect test probe. "
                "Zero model calls; not a research-quality comparison.",
            )
            sources = {
                source.source_id: store.put_artifact(
                    case["id"],
                    None,
                    "evidence",
                    f"Retained source · {source.source_id}"[:200],
                    load_blob(package / "blobs", source.artifact_sha256),
                    {"execution_eligible": False, "source_id": source.source_id},
                )
                for source in scope.sources
            }
            # The baseline receives no reference object, path or expected values.
            baseline = project_mechanical_dossier(scope, sources)
            validation = validate_dossier(baseline, {a["id"]: a for a in sources.values()})
            if not validation.valid:
                raise ValueError("Deterministic baseline failed source attribution")
            probe = deepcopy(baseline.model_dump(mode="json"))
            first_count = next(
                observation
                for observation in probe["observations"]
                if observation["kind"] == "population_count"
                and observation["count"]["state"] == "present"
            )
            first_count["count"]["value"] += 1
            artifacts = []
            for name, dossier in (
                ("Deliberately incorrect test probe", probe),
                ("Deterministic public-input baseline", baseline.model_dump(mode="json")),
            ):
                artifacts.append(
                    store.put_artifact(
                        case["id"],
                        None,
                        "clinical_dossier",
                        name,
                        {"dossier": dossier},
                        {"execution_eligible": False, "origin": name, "model_calls": 0},
                    )
                )
            reference = load_blob(package / "blobs", item["reference_sha256"])
            comparison = evaluate_mechanical_comparison(
                store,
                candidate_id=artifacts[0]["id"],
                baseline_id=artifacts[1]["id"],
                scope=scope,
                reference=reference,
                source_bindings={sid: source["id"] for sid, source in sources.items()},
                case_id=case["id"],
                key=scope.case_id,
            )
            report = comparison["content"]
            expected = report["baseline"]["expected_fields"]
            if report["baseline"]["matched_fields"] != expected or (
                report["candidate"]["matched_fields"] != expected - 1
            ):
                raise ValueError("Controlled mutation was not isolated to the intended field")
            results.append(
                {
                    "dataset_case_id": scope.case_id,
                    "case_id": case["id"],
                    "comparison_id": comparison["id"],
                    "comparison_sha256": comparison["sha256"],
                    "baseline_matched": expected,
                    "probe_matched": expected - 1,
                    "expected_fields": expected,
                    "baseline_attribution_valid": validation.valid,
                }
            )
            (staging / f"{scope.case_id}.json").write_bytes(canonical_bytes(report))
        result = {
            "schema_version": "clinical-mechanical-verification.v1",
            "reference_package_sha256": index["sha256"],
            "model_calls": 0,
            "purpose": "Instrument and workflow verification using retained sources; "
            "the candidate is a deliberate error probe, not an agent output.",
            "independent_reference_review": "pending",
            "research_quality_claim": None,
            "cases": results,
        }
        (staging / "verification.json").write_bytes(canonical_bytes(result))
        store.close()
        os.rename(staging, output)
        return result
    finally:
        store.close()
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(canonical_bytes(verify(args.package, args.output)).decode())
