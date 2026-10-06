"""Independent audit checks with explicitly synthetic builder input packages."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Reuse only synthetic package construction. The executable auditor has no
# ResearchDesk imports and does not call this builder or its checking functions.
fixtures = load_module(
    "reference_package_test_fixtures", ROOT / "tests/test_mechanical_reference_package.py"
)
builder = fixtures.builder
synthetic_package = fixtures.synthetic_package
audit = load_module(
    "independent_reference_audit", ROOT / "examples/audit_mechanical_reference_package.py"
)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


@pytest.fixture
def package(builder, synthetic_package, tmp_path):
    original, manifest, _ = synthetic_package()
    output = tmp_path / "references"
    builder.build_package(
        original, output, expected_manifest_sha256=manifest.sha256, created_at=fixtures.STAMP
    )
    return output


def mutate_and_rehash(package, mutation):
    """Make a self-consistent bad package, not just an easily caught stale hash."""
    index = json.loads((package / "package-index.json").read_text())
    sources = {
        s["source_id"]: json.loads(
            (package / "blobs" / (s["artifact_sha256"] + ".json")).read_text()
        )
        for s in index["sources"]
    }
    cases = []
    for case in index["cases"]:
        cases.append(
            (
                case,
                json.loads((package / case["scope_file"]).read_text()),
                json.loads((package / case["reference_file"]).read_text()),
                json.loads(
                    (
                        package / "blobs" / (case["projection_source"]["artifact_sha256"] + ".json")
                    ).read_text()
                ),
            )
        )
    mutation(index, sources, cases)
    blobs = {}
    source_hashes = {}
    for source in index["sources"]:
        content = sources[source["source_id"]]
        digest = sha(content)
        blobs[digest] = content
        source_hashes[source["source_id"]] = digest
        source.update(artifact_sha256=digest, artifact_id="sha256:" + digest)
    for case, scope, reference, ledger in cases:
        for source in scope["sources"]:
            source["artifact_sha256"] = source_hashes[source["source_id"]]
        case["sources"] = scope["sources"]
        case["scope_sha256"] = reference["scope_sha256"] = sha(scope)
        case["reference_sha256"] = sha(reference)
        case["fields"], case["observations"] = len(scope["fields"]), len(scope["observations"])
        ledger.update(
            scope_sha256=sha(scope),
            reference_sha256=sha(reference),
            public_source_bindings=scope["sources"],
            context_bindings=scope["contexts"],
            observation_bindings=scope["observations"],
        )
        refs = {f["field_id"]: f for f in reference["fields"]}
        ledger["field_ledger"] = [
            {"scope": f, "reference": refs[f["field_id"]]} for f in scope["fields"]
        ]
        digest = sha(ledger)
        case["projection_source"].update(artifact_sha256=digest, artifact_id="sha256:" + digest)
        blobs.update({sha(scope): scope, sha(reference): reference, digest: ledger})
        (package / case["scope_file"]).write_bytes(encoded(scope))
        (package / case["reference_file"]).write_bytes(encoded(reference))
    index["blob_sha256"] = sorted(blobs)
    index["sha256"] = sha({k: v for k, v in index.items() if k != "sha256"})
    for digest, content in blobs.items():
        (package / "blobs" / (digest + ".json")).write_bytes(encoded(content))
    (package / "package-index.json").write_bytes(encoded(index))


def test_receipt_binds_all_fields_without_answers_or_source_writes(package, tmp_path):
    before = {p.relative_to(package): p.read_bytes() for p in package.rglob("*.json")}
    receipt = audit.audit_package(package)
    assert receipt["status"] == "verified"
    assert receipt["counts"] == {
        "sources": 6,
        "blobs": 15,
        "contexts": 13,
        "observations": 20,
        "fields": 38,
        "group_endpoint_bindings": 5,
    }
    index = json.loads((package / "package-index.json").read_text())
    assert receipt["package_sha256"] == index["sha256"]
    assert [c["scope_sha256"] for c in receipt["cases"]] == [
        c["scope_sha256"] for c in index["cases"]
    ]
    assert [c["reference_sha256"] for c in receipt["cases"]] == [
        c["reference_sha256"] for c in index["cases"]
    ]
    assert "expected_value" not in json.dumps(receipt)
    assert "Synthetic endpoint alpha" not in json.dumps(receipt)
    assert receipt["reviewer"]["expert_adjudication"] is False
    output = tmp_path / "receipt.json"
    audit.write_receipt(output, receipt)
    assert json.loads(output.read_text()) == receipt
    assert output.stat().st_mode & 0o777 == 0o600
    assert before == {p.relative_to(package): p.read_bytes() for p in package.rglob("*.json")}


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda i, s, c: c[0][2]["fields"][0].update(expected_value=72),
            "reference_value_mismatch",
        ),
        (
            lambda i, s, c: c[0][2]["fields"][0].update(expected_value=True),
            "reference_value_mismatch",
        ),
        (lambda i, s, c: c[0][1]["contexts"][0].update(trial_id="NCT00045968"), "trial_identity"),
        (
            lambda i, s, c: c[0][1]["observations"][3]["group"].update(local_id="fixture-A"),
            "count_group_binding",
        ),
        (
            lambda i, s, c: c[0][1]["observations"][3].update(
                endpoint_observation_id=c[0][1]["observations"][5]["observation_id"]
            ),
            "endpoint_binding",
        ),
        (
            lambda i, s, c: c[0][1]["fields"][1]["enum_map"][0].update(value="estimated"),
            "incorrect_public_enum_map",
        ),
        (
            lambda i, s, c: c[0][1]["fields"][1]["enum_map"].append(
                c[0][1]["fields"][1]["enum_map"][0].copy()
            ),
            "duplicate_identity",
        ),
        (
            lambda i, s, c: s["ctg-NCT05643742-current-20261005"]["record"].update(
                resultsSection={}
            ),
            "absence_not_proven",
        ),
        (
            lambda i, s, c: c[1][2]["fields"][-1].update(source_path="/record/missing"),
            "absence_parent_key",
        ),
    ],
)
def test_rehashed_wrong_facts_or_bindings_fail(package, mutation, code):
    mutate_and_rehash(package, mutation)
    with pytest.raises(audit.AuditError, match=code):
        audit.audit_package(package)


def test_overlong_count_rejected_even_with_matching_label_and_hashes(package):
    def mutation(index, sources, cases):
        sources["ctg-NCT03525444-current-20261005"]["record"]["resultsSection"][
            "outcomeMeasuresModule"
        ]["outcomeMeasures"][0]["denoms"][0]["counts"][0]["value"] = "1" * 21
        cases[0][2]["fields"][7]["expected_value"] = int("1" * 21)

    mutate_and_rehash(package, mutation)
    with pytest.raises(audit.AuditError, match="invalid_canonical_count"):
        audit.audit_package(package)


def test_reduced_denominator_cannot_be_certified(package):
    def mutation(index, sources, cases):
        cases[0][1]["fields"].pop()
        cases[0][2]["fields"].pop()

    mutate_and_rehash(package, mutation)
    with pytest.raises(audit.AuditError, match="bounded_field_inventory"):
        audit.audit_package(package)


def test_failed_cli_leaves_no_receipt_and_does_not_echo_source(package, tmp_path, capsys):
    index = json.loads((package / "package-index.json").read_text())
    path = package / "blobs" / (index["sources"][0]["artifact_sha256"] + ".json")
    path.write_text('{"private_marker":"DO_NOT_ECHO"}')
    output = tmp_path / "failed.json"
    assert audit.main(["--package", str(package), "--output", str(output)]) == 1
    assert not output.exists()
    stderr = capsys.readouterr().err
    assert "blob_content_hash" in stderr and "DO_NOT_ECHO" not in stderr


def test_receipt_is_exclusive_and_cannot_write_inside_package(package, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("existing output")
    assert audit.main(["--package", str(package), "--output", str(output)]) == 1
    assert output.read_text() == "existing output"
    inside = package / "receipt.json"
    assert audit.main(["--package", str(package), "--output", str(inside)]) == 1
    assert not inside.exists()


def test_duplicate_json_keys_fail_before_receipt(package, tmp_path):
    (package / "package-index.json").write_text('{"schema_version":"a","schema_version":"b"}')
    with pytest.raises(audit.AuditError, match="duplicate_json_key"):
        audit.audit_package(package)
