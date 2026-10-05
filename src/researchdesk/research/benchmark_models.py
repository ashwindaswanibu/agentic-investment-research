"""Frozen clinical benchmark declarations, not evidence of research quality.

Hashes bind canonical JSON to a declared protocol. Availability timestamps and
independent adjudication are operator assertions: these schemas cannot verify
either from a model's answer. Public payloads deliberately exclude references.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_serializer,
    model_validator,
)

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(min_length=1, max_length=12000)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Arm = Literal["generalist", "fixed_specialists", "adaptive_specialists"]
ALL_ARMS = ("generalist", "fixed_specialists", "adaptive_specialists")


def _aware(value: datetime | None) -> datetime | None:
    if value is not None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)
    return None


def _unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def _groups(values):
    # IDs still require a curated issuer/study-family mapping. Case normalization
    # catches trivial aliases; it cannot discover subsidiaries or related trials.
    return {value.casefold() for value in values}


class FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )

    @property
    def sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BenchmarkSource(FrozenContract):
    source_id: Identifier
    version: Identifier
    kind: Literal["evidence", "programmatic_reference"]
    artifact_id: Identifier
    artifact_sha256: Sha256
    public_url: HttpUrl
    acquired_at: datetime
    published_at: datetime | None = None
    available_at: datetime | None = Field(
        default=None,
        description="Verified availability of this exact source version, not its acquisition date.",
    )

    _timestamps = field_validator("acquired_at", "published_at", "available_at")(_aware)

    @field_validator("public_url")
    @classmethod
    def no_embedded_credentials(cls, value):
        if value.username is not None or value.password is not None:
            raise ValueError("public_url must not contain credentials")
        return value

    @model_validator(mode="after")
    def chronology(self):
        if self.available_at is not None and self.available_at > self.acquired_at:
            raise ValueError("available_at cannot be after acquired_at")
        return self


class BenchmarkCase(FrozenContract):
    case_id: Identifier
    question: Text
    issuer_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    trial_family_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    split: Literal["development", "final"]
    source_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=200)
    reference_id: Identifier | None = None
    reference_sha256: Sha256 | None = None
    reference_method: Literal["programmatic", "independently_adjudicated", "unlabelled"]
    reference_source_ids: tuple[Identifier, ...] = Field(default=(), max_length=200)
    scope: Literal["extraction_only", "dossier_review"]
    information_cutoff: datetime | None = None
    historical_as_of: bool = Field(default=False, strict=True)

    _cutoff = field_validator("information_cutoff")(_aware)

    @model_validator(mode="after")
    def identities_and_scope(self):
        for name in ("issuer_ids", "trial_family_ids", "source_ids", "reference_source_ids"):
            values = getattr(self, name)
            _unique(tuple(value.casefold() for value in values), name)
        if self.reference_method == "unlabelled":
            if self.reference_id or self.reference_sha256 or self.reference_source_ids:
                raise ValueError("unlabelled cases cannot declare reference identities or sources")
        elif self.reference_id is None or self.reference_sha256 is None:
            raise ValueError("labelled cases require reference_id and reference_sha256")
        if self.reference_method == "programmatic" and not self.reference_source_ids:
            raise ValueError("programmatic references require reference_source_ids")
        if self.scope == "dossier_review" and self.reference_method != "independently_adjudicated":
            raise ValueError("dossier_review requires an independently_adjudicated reference")
        if self.historical_as_of and self.information_cutoff is None:
            raise ValueError("historical_as_of requires information_cutoff")
        return self


class DatasetManifest(FrozenContract):
    schema_version: Literal["research-benchmark-dataset.v1"] = "research-benchmark-dataset.v1"
    suite_id: Identifier
    version: Identifier
    created_at: datetime
    sources: tuple[BenchmarkSource, ...] = Field(min_length=1, max_length=20000)
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1, max_length=10000)

    _created = field_validator("created_at")(_aware)

    @model_validator(mode="after")
    def integrity(self):
        _unique(tuple(source.source_id for source in self.sources), "source IDs")
        _unique(tuple(source.artifact_id for source in self.sources), "source artifact IDs")
        _unique(tuple(case.case_id for case in self.cases), "case IDs")
        sources = {source.source_id: source for source in self.sources}
        reference_ids = {case.reference_id for case in self.cases if case.reference_id}
        reference_hashes = {case.reference_sha256 for case in self.cases if case.reference_sha256}
        split_keys = {split: set() for split in ("development", "final")}
        issuers = {split: set() for split in split_keys}
        families = {split: set() for split in split_keys}
        for source in self.sources:
            if source.acquired_at > self.created_at:
                raise ValueError("source acquisition cannot be after manifest creation")
        for case in self.cases:
            requested = (*case.source_ids, *case.reference_source_ids)
            unknown = set(requested) - sources.keys()
            if unknown:
                raise ValueError(f"case {case.case_id}: unknown source IDs {sorted(unknown)}")
            if any(sources[key].kind != "evidence" for key in case.source_ids):
                raise ValueError(
                    f"case {case.case_id}: public source_ids must contain evidence only"
                )
            if any(
                sources[key].artifact_id in reference_ids
                or sources[key].artifact_sha256 in reference_hashes
                for key in case.source_ids
            ):
                raise ValueError("reference labels cannot be included as public input evidence")
            if case.reference_method == "programmatic" and any(
                sources[key].kind != "programmatic_reference" for key in case.reference_source_ids
            ):
                raise ValueError(
                    "programmatic reference_source_ids must name programmatic_reference"
                )
            if case.information_cutoff is not None:
                # Reference labels may be prepared after the cutoff, but no input
                # evidence version may silently cross it. Publication/acquisition
                # times are not substitutes for exact-version availability.
                for key in case.source_ids:
                    source = sources[key]
                    if source.available_at is None:
                        raise ValueError(
                            f"case {case.case_id}: cutoff requires source available_at"
                        )
                    if source.available_at > case.information_cutoff:
                        raise ValueError(f"case {case.case_id}: source available after cutoff")
            issuers[case.split].update(_groups(case.issuer_ids))
            families[case.split].update(_groups(case.trial_family_ids))
            keys = split_keys[case.split]
            for key in requested:
                source = sources[key]
                url = urlsplit(str(source.public_url))
                public_identity = urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
                keys.update(
                    {
                        ("source", source.source_id),
                        ("artifact", source.artifact_id),
                        ("digest", source.artifact_sha256),
                        ("url", public_identity),
                    }
                )
            if case.reference_id:
                keys.add(("artifact", case.reference_id))
                keys.add(("digest", case.reference_sha256))
        if issuers["development"] & issuers["final"]:
            raise ValueError("issuer IDs must be disjoint between development and final")
        if families["development"] & families["final"]:
            raise ValueError("trial family IDs must be disjoint between development and final")
        if split_keys["development"] & split_keys["final"]:
            raise ValueError("source/reference identities must be disjoint between splits")
        return self


class BenchmarkBudget(FrozenContract):
    max_tool_calls: int = Field(
        ge=1, le=200, strict=True, description="Shared across all tasks in one attempt."
    )
    max_model_calls: int = Field(
        ge=1, le=500, strict=True, description="Shared across all tasks in one attempt."
    )
    max_turns_per_task: int = Field(ge=1, le=100, strict=True)
    max_output_tokens: int = Field(
        ge=1, le=32000, strict=True, description="Per model call; requires provider enforcement."
    )
    max_elapsed_seconds: int = Field(ge=30, le=7200, strict=True)


class FixedSpecialistInstructions(FrozenContract):
    researcher: Text
    coder: Text
    reviewer: Text


class PublicScopeBinding(FrozenContract):
    case_id: Identifier
    scope_id: Identifier
    scope_sha256: Sha256


class BenchmarkProtocol(FrozenContract):
    """One resource envelope/model for all arms; grading declarations are not executed here."""

    schema_version: Literal["research-benchmark-protocol.v1"] = "research-benchmark-protocol.v1"
    comparison: Literal["frozen-clinical-profile-adaptation.v1"] = (
        "frozen-clinical-profile-adaptation.v1"
    )
    protocol_id: Identifier
    version: Identifier
    created_at: datetime
    dataset_manifest_sha256: Sha256
    backend: Identifier
    model: Identifier
    budget: BenchmarkBudget
    arms: tuple[Arm, ...] = ALL_ARMS
    repetitions: int = Field(ge=1, le=100, strict=True)
    common_instructions: Text
    fixed_specialist_instructions: FixedSpecialistInstructions
    predeclared_metrics: tuple[Text, ...] = Field(min_length=1, max_length=100)
    decision_limits: tuple[Text, ...] = Field(min_length=1, max_length=100)
    stopping_criteria: tuple[Text, ...] = Field(min_length=1, max_length=100)
    public_scopes: tuple[PublicScopeBinding, ...] = Field(default=(), max_length=10000)

    _created = field_validator("created_at")(_aware)

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        # Existing frozen protocols predate this optional input. Their canonical
        # bytes and hashes must remain unchanged when no scope was declared.
        value = handler(self)
        if not self.public_scopes:
            value.pop("public_scopes", None)
        return value

    @model_validator(mode="after")
    def comparisons(self):
        if len(self.arms) != 3 or set(self.arms) != set(ALL_ARMS):
            raise ValueError("protocol must include each comparison arm exactly once")
        for name in ("predeclared_metrics", "decision_limits", "stopping_criteria"):
            _unique(getattr(self, name), name)
        _unique(tuple(item.case_id for item in self.public_scopes), "Scoped case IDs")
        _unique(tuple(item.scope_id for item in self.public_scopes), "Public scope IDs")
        return self


def validate_benchmark(
    manifest: DatasetManifest | dict, protocol: BenchmarkProtocol | dict
) -> tuple[DatasetManifest, BenchmarkProtocol]:
    """Check the dataset binding; runtime budget enforcement belongs to the runner."""
    manifest = DatasetManifest.model_validate(manifest)
    protocol = BenchmarkProtocol.model_validate(protocol)
    if protocol.dataset_manifest_sha256 != manifest.sha256:
        raise ValueError("protocol dataset_manifest_sha256 does not match the manifest")
    if protocol.created_at < manifest.created_at:
        raise ValueError("protocol creation cannot precede the frozen dataset manifest")
    if protocol.public_scopes and {item.case_id for item in protocol.public_scopes} != {
        case.case_id for case in manifest.cases
    }:
        raise ValueError("a guided protocol must declare one public scope for every case")
    return manifest, protocol


def public_case_payload(case: BenchmarkCase, manifest: DatasetManifest) -> dict:
    """Allowlist candidate-visible fields; labels and reference identities stay private."""
    registered = next((item for item in manifest.cases if item.case_id == case.case_id), None)
    if registered != case:
        raise ValueError("case must match an exact case in the frozen manifest")
    sources = {source.source_id: source for source in manifest.sources}
    return {
        "case_id": case.case_id,
        "question": case.question,
        "information_cutoff": (
            case.information_cutoff.isoformat() if case.information_cutoff is not None else None
        ),
        "historical_as_of": case.historical_as_of,
        "sources": [sources[key].model_dump(mode="json") for key in case.source_ids],
    }
