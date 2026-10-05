"""Source-qualified clinical observations, not clinical truth or scored references.

Contexts identify a retained source/analysis location. They do not merge a trial's
different reported designs, populations, groups or endpoints. Semantic evidence
checks and cross-record links belong to the dossier validator.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, StrictBool, model_validator

from .models import (
    ClinicalClaim,
    ClinicalForecast,
    Contract,
    Identifier,
    MissingInput,
    Sha256,
    SourceReference,
    Text,
)


def _json_pointer(value: str) -> str:
    if value and (not value.startswith("/") or re.search(r"~(?![01])", value)):
        raise ValueError("Use an RFC 6901 JSON pointer, including valid ~0/~1 escapes")
    return value


JsonPointer = Annotated[str, Field(max_length=1000), AfterValidator(_json_pointer)]


class ObservationContract(Contract):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class SourceAnchor(ObservationContract):
    """Exact retained artifact and pointer; containers are permitted, without quotations."""

    # Whitespace in JSON keys is significant; never normalize pointer spelling.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)

    artifact_id: Identifier
    artifact_sha256: Sha256
    source_path: JsonPointer


class MissingKeyProof(ObservationContract):
    """Assertion for validation: parent resolves to an object lacking the exact key.

    This is scoped JSON-key absence, never absence from a whole study or literature.
    A missing parent or invalid source is a failed check, not evidence of absence.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)

    parent: SourceAnchor
    key: Annotated[str, Field(max_length=1000)]


class PresentValue[T](ObservationContract):
    """The value must be supplied. Null is valid only when T explicitly permits it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)

    state: Literal["present"]
    value: T


class UnresolvedValue(ObservationContract):
    state: Literal["unresolved"]
    reason: Text


class NotApplicableValue(ObservationContract):
    state: Literal["not_applicable"]
    reason: Text


class SourceAbsentValue(ObservationContract):
    state: Literal["source_absent"]
    reason: Text
    proof: MissingKeyProof


type FieldValue[T] = Annotated[
    PresentValue[T] | UnresolvedValue | NotApplicableValue | SourceAbsentValue,
    Field(discriminator="state"),
]


class TrialIdentity(ObservationContract):
    trial_id: Identifier
    trial_family_id: Identifier


class ObservationContext(ObservationContract):
    context_id: Identifier
    trial_id: Identifier
    source: SourceAnchor = Field(
        description="Exact source container for this analysis. For observations using local "
        "group IDs, this must be the container owning the groups array, not a broader root."
    )
    kind: Literal[
        "study_design",
        "participant_flow",
        "baseline",
        "outcome_analysis",
        "publication_analysis",
        "other",
    ]
    label: Text = Field(description="Organizational label, not an uncited clinical conclusion.")
    analysis_id: Identifier | None = Field(
        default=None,
        description="Public analysis identity; does not establish cross-source equivalence.",
    )


class GroupLocator(ObservationContract):
    """A local group ID is meaningful only inside its exact source container.

    For registry outcomes, container points to the individual outcome record, not
    the overall outcome module. The same OG000 can name different treatments.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)

    container: SourceAnchor
    local_id: Identifier

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.container.artifact_sha256, self.container.source_path, self.local_id)


def _has_present(value: object) -> bool:
    if isinstance(value, PresentValue):
        return True
    if isinstance(value, list):
        return any(_has_present(item) for item in value)
    return False


class CitedObservation(ObservationContract):
    observation_id: Identifier
    context_id: Identifier
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def present_facts_have_citations(self):
        if any(_has_present(value) for value in self.__dict__.values()) and not self.source_refs:
            raise ValueError("An observation containing present facts requires source_refs")
        return self


class DesignObservation(CitedObservation):
    kind: Literal["design"]
    design_scope: Literal["trial_assignment", "analysis_comparison"]
    study_type: FieldValue[Literal["interventional", "observational", "expanded_access", "other"]]
    allocation: FieldValue[Literal["randomized", "nonrandomized"]]
    intervention_model: FieldValue[Text]
    masking: FieldValue[Text]
    phase: FieldValue[Text]
    comparator_source: FieldValue[Literal["concurrent_internal", "external", "hybrid", "other"]]


PopulationStage = Literal[
    "enrolled",
    "randomized",
    "dosed",
    "started",
    "completed",
    "not_completed",
    "analyzed",
    "safety_set",
    "other",
]


def _distinct_stages(values: list[PopulationStage]) -> list[PopulationStage]:
    if len(values) != len(set(values)):
        raise ValueError("Population stages must be distinct")
    return values


PopulationStages = Annotated[
    list[PopulationStage], Field(min_length=1, max_length=9), AfterValidator(_distinct_stages)
]
ParticipantCount = Annotated[int, Field(ge=0, strict=True)]


class PopulationCountObservation(CitedObservation):
    kind: Literal["population_count"]
    group: GroupLocator | None = Field(
        description="Null denotes a population without a local group."
    )
    count: FieldValue[ParticipantCount | None]
    count_normalization: Literal["none", "integer_from_digit_string", "reported_in_text"]
    count_source_ref: SourceReference | None = None
    unit: FieldValue[Text]
    population_definition: FieldValue[Text]
    reported_stage: FieldValue[Text]
    stages: FieldValue[PopulationStages] = Field(
        description="Conjunction: each tag describes the same population; do not add counts."
    )
    assignment_basis: FieldValue[Literal["as_assigned", "actual_treatment_received", "other"]]
    reported_status: FieldValue[Literal["actual", "estimated"]]
    endpoint_observation_id: Identifier | None = None

    @model_validator(mode="after")
    def normalization_applies_only_to_present_numbers(self):
        if self.count.state == "present" and self.count_source_ref is None:
            raise ValueError("A present count, including null, requires count_source_ref")
        if self.count.state != "present" and self.count_source_ref is not None:
            raise ValueError("A nonpresent count cannot supply count_source_ref")
        if (self.count.state != "present" or self.count.value is None) and (
            self.count_normalization != "none"
        ):
            raise ValueError("Only a present numeric count can declare a normalization")
        return self


class EndpointObservation(CitedObservation):
    kind: Literal["endpoint"]
    definition: FieldValue[Text]
    reported_role: FieldValue[Literal["primary", "secondary", "other"]]
    timeframe: FieldValue[Text]
    time_origin: FieldValue[Text]
    population_definition: FieldValue[Text]
    comparator_description: FieldValue[Text]
    population_count_ids: list[Identifier] = Field(max_length=100)
    groups: list[GroupLocator] = Field(max_length=100)
    prespecification: FieldValue[Literal["yes", "no"]]
    prespecification_refs: list[SourceReference] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def prespecification_has_separate_support(self):
        if self.prespecification.state == "present" and not self.prespecification_refs:
            raise ValueError("Present prespecification requires separate prespecification_refs")
        return self


class AvailabilityObservation(CitedObservation):
    kind: Literal["availability"]
    subject: Literal[
        "registry_results", "protocol", "statistical_analysis_plan", "publication", "other"
    ]
    available: FieldValue[StrictBool | None] = Field(
        description="Present null preserves an explicit source null; it does not mean unavailable."
    )
    available_source_ref: SourceReference | None = None
    scope_description: Text

    @model_validator(mode="after")
    def present_availability_has_exact_binding(self):
        if self.available.state == "present" and self.available_source_ref is None:
            raise ValueError("Present availability, including null, requires available_source_ref")
        if self.available.state != "present" and self.available_source_ref is not None:
            raise ValueError("Nonpresent availability cannot supply available_source_ref")
        return self


ClinicalObservation = Annotated[
    DesignObservation | PopulationCountObservation | EndpointObservation | AvailabilityObservation,
    Field(discriminator="kind"),
]


class Reconciliation(ObservationContract):
    observation_ids: list[Identifier] = Field(min_length=2, max_length=50)
    relationship: Literal["compatible_contexts", "unresolved_difference", "conflicting_same_scope"]
    explanation: Text
    kind: Literal["fact", "inference"]
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=30)
    inference_basis: Text | None = None

    @model_validator(mode="after")
    def distinct_inputs_and_declared_basis(self):
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("Reconciliation requires distinct observation IDs")
        if self.kind == "fact" and not self.source_refs:
            raise ValueError("A source-reported reconciliation requires source_refs")
        if self.kind == "inference" and not self.inference_basis:
            raise ValueError("An inferred reconciliation requires inference_basis")
        if self.kind == "fact" and self.inference_basis is not None:
            raise ValueError("A fact cannot simultaneously supply an inference_basis")
        return self


class ClinicalDossierV2(ObservationContract):
    """A source-qualified live output; deliberately not a flattened scoring reference.

    Citation/anchor resolution, cross-ID integrity and global source/output limits
    are checked by the validation service against retained evidence artifacts.
    """

    schema_version: Literal["clinical-dossier.v2"] = "clinical-dossier.v2"
    intervention: Text
    indication: Text
    population: Text
    trials: list[TrialIdentity] = Field(min_length=1, max_length=50)
    contexts: list[ObservationContext] = Field(min_length=1, max_length=150)
    observations: list[ClinicalObservation] = Field(min_length=1, max_length=300)
    reconciliations: list[Reconciliation] = Field(max_length=100)
    claims: list[ClinicalClaim] = Field(min_length=1, max_length=300)
    contrary_evidence_claim_ids: list[Identifier] = Field(max_length=300)
    contrary_evidence_summary: Text
    missing_inputs: list[MissingInput] = Field(max_length=100)
    uncertainty: list[Text] = Field(min_length=1, max_length=100)
    forecast: ClinicalForecast | None = Field(
        description="Explicit null for an extraction-only dossier. When a forecast is requested, "
        "provide its falsifiable target and real dates or an explicit abstention; never invent "
        "forecast dates to satisfy the output schema."
    )
