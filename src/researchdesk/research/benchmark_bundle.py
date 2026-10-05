"""Content-addressed, operator-owned inputs for frozen research evaluations.

Source artifact hashes cover canonical JSON, not the provider's raw HTTP bytes.
Connector provenance must separately retain raw-byte hashes. Reference files are
never imported into an agent store. A digest detects changes; it is not a signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from researchdesk.store import content_hash

from .benchmark_models import DatasetManifest, validate_benchmark

MAX_FILE_BYTES = 2_000_000
MAX_BUNDLE_BYTES = 100_000_000


def canonical_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def read_json(path: Path, maximum=MAX_FILE_BYTES):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON keys are not accepted")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("JSON numbers must be finite")

    # Bound actual bytes read, not only a prior stat susceptible to file growth.
    path = path.absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("A self-contained bundle cannot use symlink paths")
    if not path.is_file():
        raise ValueError("Expected a regular JSON file, not a symlink")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("JSON file exceeds its size limit")
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    canonical_bytes(value)  # Also rejects overflowed numeric literals such as 1e999.
    return value


def implementation_sha256() -> str:
    """Bind the installed Python package, including the runner and evaluator."""
    root = Path(__file__).resolve().parents[1]
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }
    return content_hash(hashes)


def _digests(manifest: DatasetManifest, protocol=None) -> set[str]:
    digests = {s.artifact_sha256 for s in manifest.sources} | {
        c.reference_sha256 for c in manifest.cases if c.reference_sha256
    }
    if protocol is not None:
        digests.update(item.scope_sha256 for item in protocol.public_scopes)
    return digests


def load_public_scope(blobs, manifest, protocol, case):
    """Load only the explicitly declared public contract, never the answer key."""
    from .scoped_models import MechanicalScope

    binding = next((item for item in protocol.public_scopes if item.case_id == case.case_id), None)
    if binding is None:
        return None
    scope = MechanicalScope.model_validate(load_blob(blobs, binding.scope_sha256))
    if (
        scope.scope_id != binding.scope_id
        or scope.case_id != case.case_id
        or scope.sha256 != binding.scope_sha256
    ):
        raise ValueError("Public scope identity differs from its protocol binding")
    sources = {source.source_id: source for source in manifest.sources}
    for source in scope.sources:
        if source.source_id not in case.source_ids or (
            sources[source.source_id].artifact_sha256 != source.artifact_sha256
        ):
            raise ValueError("Public scope must bind the case's exact public source versions")
    return scope


def _validate_scoped_references(blobs, manifest, protocol):
    from .scoped_models import MechanicalReference
    from .scoped_quality import validate_mechanical_reference

    sources = {source.source_id: source for source in manifest.sources}
    for case in manifest.cases:
        scope = load_public_scope(blobs, manifest, protocol, case)
        if scope is None:
            continue
        if case.reference_method != "programmatic":
            raise ValueError("Guided mechanical scopes require a programmatic reference")
        reference = MechanicalReference.model_validate(load_blob(blobs, case.reference_sha256))
        if reference.reference_id != case.reference_id or reference.sha256 != case.reference_sha256:
            raise ValueError("Mechanical reference identity differs from the manifest")
        artifacts = {
            item.source_id: {
                "id": sources[item.source_id].artifact_id,
                "sha256": item.artifact_sha256,
                "kind": "evidence",
                "content": load_blob(blobs, item.artifact_sha256),
            }
            for item in scope.sources
        }
        validate_mechanical_reference(scope, reference, artifacts)


def load_blob(blobs: Path, digest: str):
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("Invalid content digest")
    content = read_json(blobs / f"{digest}.json")
    if content_hash(content) != digest:
        raise ValueError("Source or reference blob failed integrity verification")
    # Match Store's encoded-content bound, including escaped non-ASCII text.
    if len(json.dumps(content, allow_nan=False).encode()) > MAX_FILE_BYTES:
        raise ValueError("Blob exceeds the agent artifact storage limit")
    return content


def freeze_bundle(*, manifest_path: Path, protocol_path: Path, blobs: Path, output: Path) -> dict:
    """Validate everything before atomically publishing a new local bundle."""
    manifest, protocol = validate_benchmark(read_json(manifest_path), read_json(protocol_path))
    if output.exists():
        raise ValueError("Output already exists; create a new version instead of overwriting")
    content = {}
    total = 0
    for digest in sorted(_digests(manifest, protocol)):
        value = load_blob(blobs, digest)
        encoded = canonical_bytes(value)
        total += len(encoded)
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle exceeds the 100 MB content limit")
        content[digest] = encoded
    _validate_scoped_references(blobs, manifest, protocol)
    binding = {
        "schema_version": "research-benchmark-bundle.v1",
        "manifest_sha256": manifest.sha256,
        "protocol_sha256": protocol.sha256,
        "implementation_sha256": implementation_sha256(),
        "blob_sha256": sorted(content),
        "scope": "frozen evidence; profile adaptation; no generated-tool qualification",
        "reference_validation": (
            "scoped source projection verified; no expert adjudication or clinical score certified"
            if protocol.public_scopes
            else "byte binding only; no gold validity or clinical score certified"
        ),
    }
    receipt = {**binding, "sha256": content_hash(binding)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".benchmark-freeze-", dir=output.parent))
    try:
        (temporary / "blobs").mkdir()
        for digest, encoded in content.items():
            (temporary / "blobs" / f"{digest}.json").write_bytes(encoded)
        for name, value in (
            ("manifest", manifest.model_dump(mode="json")),
            ("protocol", protocol.model_dump(mode="json")),
            ("binding", receipt),
        ):
            (temporary / f"{name}.json").write_bytes(canonical_bytes(value))
        # Validate the materialized package too; no partial bundle is a valid run input.
        load_bundle(temporary)
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return receipt


def load_bundle(path: Path):
    manifest, protocol = validate_benchmark(
        read_json(path / "manifest.json"), read_json(path / "protocol.json")
    )
    binding = read_json(path / "binding.json")
    if not isinstance(binding, dict):
        raise ValueError("Malformed bundle binding")
    receipt = dict(binding)
    digest = receipt.pop("sha256", None)
    if (
        digest != content_hash(receipt)
        or receipt.get("schema_version") != "research-benchmark-bundle.v1"
        or receipt.get("manifest_sha256") != manifest.sha256
        or receipt.get("protocol_sha256") != protocol.sha256
        or receipt.get("implementation_sha256") != implementation_sha256()
        or receipt.get("blob_sha256") != sorted(_digests(manifest, protocol))
    ):
        raise ValueError("Bundle inputs or implementation changed; freeze a new version")
    total = 0
    for blob in receipt["blob_sha256"]:
        total += len(canonical_bytes(load_blob(path / "blobs", blob)))
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle exceeds the 100 MB content limit")
    _validate_scoped_references(path / "blobs", manifest, protocol)
    return manifest, protocol, binding
