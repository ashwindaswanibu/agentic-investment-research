"""Clinical research contracts; a valid dossier is not a clinical efficacy judgment."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

Text = Annotated[str, Field(min_length=1, max_length=12000)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReference(Contract):
    artifact_id: Identifier
    artifact_sha256: Sha256
    excerpt: Text
    source_path: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional RFC 6901 pointer to one string within the artifact content.",
    )


class ClinicalClaim(Contract):
    id: Identifier
    kind: Literal["fact", "inference"]
    statement: Text
    trial_ids: list[Identifier] = Field(min_length=1, max_length=50)
    source_refs: list[SourceReference] = Field(min_length=1, max_length=30)
    inference_basis: Text | None = None


class TrialDesign(Contract):
    study_type: Literal["interventional", "observational", "expanded_access", "unknown"]
    allocation: Literal["randomized", "nonrandomized", "not_applicable", "unknown"]
    masking: Text
    phase: Text


class TrialArm(Contract):
    arm_id: Identifier
    label: Text
    intervention: Text
    role: Literal["treatment", "comparator", "other", "unknown"]
    planned_n: int | None = Field(default=None, ge=0, strict=True)
    source_claim_ids: list[Identifier] = Field(min_length=1, max_length=30)


class TrialEndpoint(Contract):
    endpoint_id: Identifier
    name: Text
    kind: Literal["primary", "secondary", "other", "unknown"]
    timeframe: Text
    prespecified: Literal["yes", "no", "unknown"]
    source_claim_ids: list[Identifier] = Field(min_length=1, max_length=30)


class ClinicalTrial(Contract):
    trial_id: Identifier
    design: TrialDesign
    arms: list[TrialArm] = Field(min_length=1, max_length=100)
    endpoints: list[TrialEndpoint] = Field(min_length=1, max_length=100)
    source_claim_ids: list[Identifier] = Field(min_length=1, max_length=30)


class MissingInput(Contract):
    field: Text
    reason: Text
    consequence: Text


class ClinicalForecast(Contract):
    status: Literal["forecast", "abstain"]
    target: Text
    as_of: date
    horizon: date
    outcome_rule: Text
    resolution_source: Text
    prediction: Text | None = None
    probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False, strict=True)
    abstention_reason: Text | None = None


class ClinicalDossier(Contract):
    schema_version: Literal["clinical-dossier.v1"] = "clinical-dossier.v1"
    intervention: Text
    indication: Text
    population: Text
    trials: list[ClinicalTrial] = Field(min_length=1, max_length=50)
    claims: list[ClinicalClaim] = Field(min_length=1, max_length=300)
    contrary_evidence_claim_ids: list[Identifier] = Field(max_length=300)
    contrary_evidence_summary: Text
    missing_inputs: list[MissingInput] = Field(max_length=100)
    uncertainty: list[Text] = Field(min_length=1, max_length=100)
    forecast: ClinicalForecast


class QualityCheck(Contract):
    code: str
    path: str
    passed: bool
    message: str


class DossierCoverage(Contract):
    trials: int = 0
    claims: int = 0
    facts: int = 0
    inferences: int = 0
    source_references: int = 0
    verified_source_references: int = 0
    fully_attributed_claims: int = 0
    distinct_sources: int = 0
    contrary_claims: int = 0
    missing_inputs: int = 0


class DossierValidationReport(Contract):
    valid: bool = Field(description="Structure and provenance checks passed; not a truth judgment.")
    checks: list[QualityCheck]
    coverage: DossierCoverage
    limitations: list[str]

    @computed_field
    @property
    def failed_checks(self) -> list[QualityCheck]:
        return [check for check in self.checks if not check.passed]

    @computed_field
    @property
    def issues(self) -> list[QualityCheck]:
        return self.failed_checks


class ExtractedDesign(Contract):
    study_type: str | None = None
    allocation: str | None = None
    masking: str | None = None
    phase: str | None = None


class ExtractedArm(Contract):
    arm_id: Identifier
    label: str | None = None
    intervention: str | None = None
    role: str | None = None
    planned_n: int | None = Field(default=None, ge=0, strict=True)


class ExtractedEndpoint(Contract):
    endpoint_id: Identifier
    name: str | None = None
    kind: str | None = None
    timeframe: str | None = None
    prespecified: str | None = None


class ExtractedTrial(Contract):
    trial_id: Identifier
    design: ExtractedDesign = Field(default_factory=ExtractedDesign)
    arms: list[ExtractedArm] = Field(default_factory=list, max_length=100)
    endpoints: list[ExtractedEndpoint] = Field(default_factory=list, max_length=100)


class ClinicalExtraction(Contract):
    """Closed comparison scope: trial facts, excluding claims, reasoning and forecasts.

    Stable trial/arm/endpoint IDs align records regardless of order. None and blank
    fields are abstentions; the explicit string 'unknown' is a comparable assertion.
    """

    intervention: str | None = None
    indication: str | None = None
    population: str | None = None
    trials: list[ExtractedTrial] = Field(default_factory=list, max_length=50)


class ExtractionReference(Contract):
    schema_version: Literal["clinical-extraction-reference.v1"] = "clinical-extraction-reference.v1"
    coverage: Literal["complete_for_schema"]
    extraction: ClinicalExtraction
    reference_id: Identifier
    notes: Text


class FieldError(Contract):
    path: str
    code: Literal["missing_field", "unexpected_field", "value_mismatch"]
    expected: str | int | bool | None
    actual: str | int | bool | None
    critical: bool


class ExtractionScore(Contract):
    reference_id: str
    valid: bool = Field(
        description="Inputs were scorable; does not mean the extraction was correct."
    )
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    reference_fields: int
    candidate_fields: int
    errors: list[FieldError]
    critical_errors: list[FieldError]
    schema_errors: list[QualityCheck]
    limitations: list[str]
