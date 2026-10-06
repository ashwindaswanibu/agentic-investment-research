"""Public mechanical extraction scope and separate private source projections.

The scope contains identities and questions, not expected answers or reference
metadata. Private projections assess only declared fields; neither their method
nor a reviewer record establishes expert adjudication or clinical correctness.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, StringConstraints, model_validator

from .benchmark_models import FrozenContract
from .observation_models import JsonPointer

Identifier = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)
]
Text = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=12000)
]
Sha256 = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=False, pattern=r"^[0-9a-f]{64}$")
]
ExactPointer = Annotated[JsonPointer, StringConstraints(strict=True, strip_whitespace=False)]
ExactKey = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, max_length=1000)]
ExactGroupId = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=False, min_length=1, max_length=200)
]
ExactTextValue = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=False, max_length=12000)
]
MechanicalValue = ExactTextValue | StrictInt | StrictBool | None
ContextKind = Literal[
    "study_design",
    "participant_flow",
    "baseline",
    "outcome_analysis",
    "publication_analysis",
    "other",
]
ObservationKind = Literal["design", "population_count", "endpoint", "availability"]
DesignScope = Literal["trial_assignment", "analysis_comparison"]
Normalization = Literal[
    "identity", "canonical_digit_string", "lowercase_enum", "enum_lookup", "nfc_whitespace"
]
FieldName = Literal[
    "study_type",
    "allocation",
    "intervention_model",
    "masking",
    "phase",
    "comparator_source",
    "count",
    "unit",
    "population_definition",
    "reported_stage",
    "stages",
    "assignment_basis",
    "reported_status",
    "definition",
    "reported_role",
    "timeframe",
    "time_origin",
    "comparator_description",
    "prespecification",
    "available",
]
OBSERVATION_FIELDS = MappingProxyType(
    {
        "design": frozenset(
            {
                "study_type",
                "allocation",
                "intervention_model",
                "masking",
                "phase",
                "comparator_source",
            }
        ),
        "population_count": frozenset(
            {
                "count",
                "unit",
                "population_definition",
                "reported_stage",
                "stages",
                "assignment_basis",
                "reported_status",
            }
        ),
        "endpoint": frozenset(
            {
                "definition",
                "reported_role",
                "timeframe",
                "time_origin",
                "population_definition",
                "comparator_description",
                "prespecification",
            }
        ),
        "availability": frozenset({"available"}),
    }
)


def _unique(values, name: str):
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be unique")


class ScopedContract(FrozenContract):
    model_config = ConfigDict(str_strip_whitespace=False)


class ScopeSource(ScopedContract):
    source_id: Identifier
    artifact_sha256: Sha256


class ScopeContext(ScopedContract):
    context_id: Identifier
    trial_id: Identifier
    trial_family_id: Identifier
    source_id: Identifier
    source_path: ExactPointer
    kind: ContextKind
    analysis_id: Identifier | None = None


class ScopeGroup(ScopedContract):
    container_source_path: ExactPointer
    local_id: ExactGroupId


class ScopeObservation(ScopedContract):
    observation_id: Identifier
    context_id: Identifier
    kind: ObservationKind
    group: ScopeGroup | None = None
    design_scope: DesignScope | None = None
    endpoint_observation_id: Identifier | None = None

    @model_validator(mode="after")
    def kind_specific_identity(self):
        if self.kind == "design" and self.design_scope is None:
            raise ValueError("Design observations require design_scope")
        if self.kind != "design" and self.design_scope is not None:
            raise ValueError("Only design observations can declare design_scope")
        if self.kind != "population_count" and self.group is not None:
            raise ValueError("Only population_count observations can declare a public group")
        if self.kind != "population_count" and self.endpoint_observation_id is not None:
            raise ValueError("Only population_count observations can declare an endpoint link")
        return self


class EnumMapping(ScopedContract):
    source_token: Annotated[ExactTextValue, StringConstraints(min_length=1, max_length=200)]
    value: Annotated[ExactTextValue, StringConstraints(min_length=1, max_length=200)]


class ScopedField(ScopedContract):
    field_id: Identifier
    observation_id: Identifier
    field_name: FieldName
    source_path: ExactPointer = Field(
        description="Exact requested source field location, whether present or absent. "
        "This public selector does not declare the expected value or state."
    )
    question: Text
    normalization: Normalization = Field(
        default="identity",
        description="Candidate-visible source normalization declared before reference binding. "
        "This rule does not disclose an expected value or state.",
    )
    enum_map: tuple[EnumMapping, ...] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        exclude_if=lambda value: value is None,
        description="Complete field-specific source-token lookup for enum_lookup. "
        "Exact, case-sensitive tokens; not a declaration of the observed answer. "
        "Omitted for legacy scopes so their frozen hashes remain unchanged.",
    )
    severity: Literal["data_integrity", "ordinary"] = Field(
        description="Declared software/data-integrity severity, not clinical error severity."
    )

    @model_validator(mode="after")
    def declared_enum_lookup(self):
        if self.normalization == "enum_lookup":
            if not self.enum_map:
                raise ValueError("enum_lookup requires a public enum_map")
            _unique(tuple(item.source_token for item in self.enum_map), "Enum source tokens")
        elif self.enum_map is not None:
            raise ValueError("Only enum_lookup can declare enum_map")
        return self


class MechanicalScope(ScopedContract):
    """Candidate-visible identity mapping and explicit field scope, without expected answers."""

    schema_version: Literal["clinical-mechanical-scope.v1"] = "clinical-mechanical-scope.v1"
    scope_id: Identifier
    version: Identifier
    case_id: Identifier
    sources: tuple[ScopeSource, ...] = Field(min_length=1, max_length=30)
    contexts: tuple[ScopeContext, ...] = Field(min_length=1, max_length=150)
    observations: tuple[ScopeObservation, ...] = Field(min_length=1, max_length=300)
    fields: tuple[ScopedField, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def exact_identity_links(self):
        _unique(tuple(item.source_id for item in self.sources), "Source IDs")
        _unique(tuple(item.context_id for item in self.contexts), "Context IDs")
        _unique(tuple(item.observation_id for item in self.observations), "Observation IDs")
        _unique(tuple(item.field_id for item in self.fields), "Field IDs")
        _unique(
            tuple((item.observation_id, item.field_name) for item in self.fields),
            "Field targets",
        )
        sources = {item.source_id for item in self.sources}
        contexts = {item.context_id: item for item in self.contexts}
        observations = {item.observation_id: item for item in self.observations}
        trial_families: dict[str, str] = {}
        for context in self.contexts:
            if context.source_id not in sources:
                raise ValueError(f"Context {context.context_id} names an unknown source ID")
            family = trial_families.setdefault(context.trial_id, context.trial_family_id)
            if family != context.trial_family_id:
                raise ValueError("A trial ID must map to one trial family within a scope")
        for observation in self.observations:
            if observation.context_id not in contexts:
                raise ValueError(
                    f"Observation {observation.observation_id} names an unknown context ID"
                )
            context = contexts[observation.context_id]
            if (
                observation.group is not None
                and observation.group.container_source_path != context.source_path
            ):
                raise ValueError("A public group must use its context's exact source container")
            if observation.endpoint_observation_id is not None:
                endpoint = observations.get(observation.endpoint_observation_id)
                if endpoint is None or endpoint.kind != "endpoint":
                    raise ValueError("A population endpoint link must name an endpoint observation")
                if endpoint.context_id != observation.context_id:
                    raise ValueError("A population endpoint link must use the same context")
        for field in self.fields:
            if field.observation_id not in observations:
                raise ValueError(f"Field {field.field_id} names an unknown observation ID")
            kind = observations[field.observation_id].kind
            context = contexts[observations[field.observation_id].context_id]
            base = context.source_path
            if base and field.source_path != base and not field.source_path.startswith(base + "/"):
                raise ValueError("A public field selector must remain within its source context")
            if field.field_name not in OBSERVATION_FIELDS[kind]:
                raise ValueError(f"Field {field.field_name} is not a FieldValue field for {kind}")
        return self


class PresentMechanicalFieldReference(ScopedContract):
    field_id: Identifier
    expected_state: Literal["present"]
    expected_value: MechanicalValue
    source_id: Identifier
    source_path: ExactPointer
    normalization: Normalization
    source_group_path: ExactPointer | None = Field(
        default=None,
        description="Optional exact groupId selector. Required by binding validation for grouped "
        "population count values; must be a sibling of the value selector and match the public "
        "local ID. Other population fields do not require this selector.",
    )
    rationale: Text

    @model_validator(mode="after")
    def normalization_value_type(self):
        if self.normalization == "canonical_digit_string":
            if type(self.expected_value) is not int or self.expected_value < 0:
                raise ValueError("canonical_digit_string requires a nonnegative strict integer")
        elif self.normalization in {"lowercase_enum", "enum_lookup", "nfc_whitespace"}:
            if type(self.expected_value) is not str:
                raise ValueError(f"{self.normalization} requires a string")
        return self


class AbsentMechanicalFieldReference(ScopedContract):
    """The source pointer selects a parent object; exact-key absence needs source validation."""

    field_id: Identifier
    expected_state: Literal["source_absent"]
    source_id: Identifier
    source_path: ExactPointer
    normalization: Literal["identity"]
    missing_key: ExactKey
    rationale: Text


MechanicalFieldReference = Annotated[
    PresentMechanicalFieldReference | AbsentMechanicalFieldReference,
    Field(discriminator="expected_state"),
]


class ReviewerRecord(ScopedContract):
    """Attribution only: an entry does not confer trusted or expert adjudication."""

    reviewer_id: Identifier
    kind: Literal["human", "automated"]
    method: Text
    notes: Text


class MechanicalReference(ScopedContract):
    """Private programmatic projections for an explicit partial scope, never expert gold."""

    schema_version: Literal["clinical-mechanical-reference.v1"] = "clinical-mechanical-reference.v1"
    reference_id: Identifier
    scope_sha256: Sha256
    fields: tuple[MechanicalFieldReference, ...] = Field(min_length=1, max_length=1000)
    method: Literal["programmatic_source_projection"] = "programmatic_source_projection"
    limitations: tuple[Text, ...] = Field(min_length=1, max_length=100)
    reviewers: tuple[ReviewerRecord, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_reference_fields(self):
        _unique(tuple(item.field_id for item in self.fields), "Reference field IDs")
        return self
