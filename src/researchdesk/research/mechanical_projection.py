"""Deterministic copying baseline using only public scope and bound evidence.

No private reference, answer key, scorer, model, network or Store is consulted.
This is a guided extraction diagnostic, not an agent or clinical research system.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

from pydantic import TypeAdapter, ValidationError

from .models import SourceReference
from .observation_models import (
    AvailabilityObservation,
    ClinicalDossierV2,
    DesignObservation,
    EndpointObservation,
    PopulationCountObservation,
)
from .quality import (
    MAX_DOSSIER_BYTES,
    MAX_SOURCE_CONTENT_BYTES,
    _hash,
    _normalize,
    _pointer,
    _scalar_excerpt,
    bounded_json_size,
)
from .scoped_models import OBSERVATION_FIELDS, MechanicalScope

MAX_SCOPE_BYTES = 200_000
MAX_SINGLE_SOURCE_BYTES = 2_000_000
_MODELS = {
    "design": DesignObservation,
    "population_count": PopulationCountObservation,
    "endpoint": EndpointObservation,
    "availability": AvailabilityObservation,
}


class ProjectionInputError(ValueError):
    """Safe, content-free admission failure; no source interpretation was made."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _unresolved(reason):
    return {"state": "unresolved", "reason": reason}


def _anchor(source, path):
    return {
        "artifact_id": source["id"],
        "artifact_sha256": source["sha256"],
        "source_path": path,
    }


def _admit(scope, sources):
    try:
        raw = scope.model_dump(mode="json") if isinstance(scope, MechanicalScope) else scope
        bounded_json_size(raw, MAX_SCOPE_BYTES)
        scope = MechanicalScope.model_validate(raw)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ProjectionInputError("invalid_or_oversize_public_scope") from error
    if not isinstance(sources, Mapping) or set(sources) != {
        item.source_id for item in scope.sources
    }:
        raise ProjectionInputError("public_source_set_mismatch")
    admitted, identities, size = {}, set(), 0
    for item in scope.sources:
        artifact = sources[item.source_id]
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "evidence":
            raise ProjectionInputError("public_source_kind")
        identifier = artifact.get("id")
        if (
            type(identifier) is not str
            or not 1 <= len(identifier) <= 200
            or identifier in identities
        ):
            raise ProjectionInputError("public_source_identity")
        identities.add(identifier)
        try:
            content = artifact["content"]
            size += bounded_json_size(content, MAX_SINGLE_SOURCE_BYTES)
            if size > MAX_SOURCE_CONTENT_BYTES:
                raise ProjectionInputError("public_source_budget")
            if (
                artifact.get("sha256") != item.artifact_sha256
                or _hash(content) != item.artifact_sha256
            ):
                raise ProjectionInputError("public_source_integrity")
        except ProjectionInputError:
            raise
        except (KeyError, ValueError, TypeError, OverflowError, RecursionError) as error:
            raise ProjectionInputError("invalid_or_oversize_public_source") from error
        admitted[item.source_id] = artifact
    for context in scope.contexts:
        try:
            _pointer(admitted[context.source_id]["content"], context.source_path)
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise ProjectionInputError("public_context_unavailable") from error
    return scope, admitted


@lru_cache(maxsize=40)
def _field_adapter(kind, field):
    return TypeAdapter(_MODELS[kind].model_fields[field].annotation)


def _normalized(raw, operation, enum_map=None):
    if raw is not None and type(raw) not in (str, int, bool):
        raise ValueError("The requested value is not a supported exact scalar.")
    if operation == "identity":
        return raw
    if type(raw) is not str:
        raise ValueError("The declared normalization requires a source string.")
    if operation == "canonical_digit_string":
        if len(raw) > 20 or re.fullmatch(r"0|[1-9][0-9]*", raw) is None:
            raise ValueError("The source is not a canonical ASCII integer string.")
        try:
            return int(raw)
        except ValueError as error:
            raise ValueError("The source integer string exceeds the conversion bound.") from error
    if operation == "lowercase_enum":
        return raw.lower()
    if operation == "enum_lookup":
        for entry in enum_map or ():
            if raw == entry.source_token:
                return entry.value
        raise ValueError("The source token is absent from the declared public enum lookup.")
    if operation == "nfc_whitespace":
        return _normalize(raw)
    raise ValueError("The public normalization is unsupported.")


def _project_field(field, observation, source):
    path = field.source_path
    try:
        raw = _pointer(source["content"], path)
    except (KeyError, IndexError, ValueError, TypeError):
        # Only exact object-key nonmembership is an absence proof. Missing parents,
        # invalid array indexes and other lookup failures remain unresolved.
        if path:
            parent_path, _, token = path.rpartition("/")
            key = token.replace("~1", "/").replace("~0", "~")
            try:
                parent = _pointer(source["content"], parent_path)
                if type(parent) is dict and key not in parent:
                    return {
                        "state": "source_absent",
                        "reason": "Only this exact key is absent from the retained parent object; "
                        "this makes no claim about evidence elsewhere.",
                        "proof": {"parent": _anchor(source, parent_path), "key": key},
                    }, None
            except (KeyError, IndexError, ValueError, TypeError):
                pass
        return _unresolved(
            "The requested field or its parent cannot be resolved; absence is unproved."
        ), None
    try:
        if observation.group is not None and field.field_name == "count":
            group_path = path.rsplit("/", 1)[0] + "/groupId"
            if _pointer(source["content"], group_path) != observation.group.local_id:
                raise ValueError(
                    "The count's sibling groupId does not match its public group identity."
                )
        value = _normalized(raw, field.normalization, field.enum_map)
        projected = _field_adapter(observation.kind, field.field_name).validate_python(
            {"state": "present", "value": value}, strict=True
        )
        # Citations retain the raw scalar, not the normalized output. A scalar that
        # cannot fit the citation contract is not truncated into a fabricated fact.
        excerpt = raw if type(raw) is str else _scalar_excerpt(raw)
        citation = SourceReference(**_anchor(source, path), excerpt=excerpt).model_dump(mode="json")
        return projected.model_dump(mode="json"), citation
    except ValidationError:
        return _unresolved(
            "The source value cannot be represented by the requested typed field or citation."
        ), None
    except (KeyError, IndexError, ValueError, TypeError) as error:
        reason = (
            str(error)
            if type(error) is ValueError
            else "The required source/group binding is unavailable."
        )
        return _unresolved(reason), None


def project_mechanical_dossier(scope, source_artifacts_by_source_id) -> ClinicalDossierV2:
    """Copy declared public scalar fields into an explicitly limited v2 dossier.

    Source/hash/kind/budget defects and invalid public contexts reject the input.
    Within a valid context, unsupported values or unresolved parent paths produce
    explicit unresolved fields. No private expected values enter this function.
    """
    scope, sources = _admit(scope, source_artifacts_by_source_id)
    contexts = {item.context_id: item for item in scope.contexts}
    observations = {}
    for requested in scope.observations:
        context = contexts[requested.context_id]
        source = sources[context.source_id]
        item = {
            "kind": requested.kind,
            "observation_id": requested.observation_id,
            "context_id": requested.context_id,
            "source_refs": [],
            **{
                field: _unresolved(
                    "This field is outside the supplied mechanical extraction scope."
                )
                for field in OBSERVATION_FIELDS[requested.kind]
            },
        }
        if requested.kind == "design":
            item["design_scope"] = requested.design_scope
        elif requested.kind == "population_count":
            group = None
            if requested.group is not None:
                container = _pointer(source["content"], requested.group.container_source_path)
                groups = container.get("groups") if type(container) is dict else None
                matches = (
                    sum(
                        type(value) is dict and value.get("id") == requested.group.local_id
                        for value in groups
                    )
                    if type(groups) is list
                    else 0
                )
                if matches != 1:
                    raise ProjectionInputError("public_group_identity")
                group = {
                    "container": _anchor(source, requested.group.container_source_path),
                    "local_id": requested.group.local_id,
                }
            item.update(
                group=group,
                count_normalization="none",
                count_source_ref=None,
                endpoint_observation_id=requested.endpoint_observation_id,
            )
        elif requested.kind == "endpoint":
            item.update(population_count_ids=[], groups=[], prespecification_refs=[])
        elif requested.kind == "availability":
            item.update(
                subject="other",
                available_source_ref=None,
                scope_description="Only the exact field requested by the public mechanical scope "
                "in this retained source; no literature-wide availability judgment.",
            )
        observations[requested.observation_id] = item
    requested_observations = {item.observation_id: item for item in scope.observations}
    for field in scope.fields:
        requested = requested_observations[field.observation_id]
        context = contexts[requested.context_id]
        item = observations[field.observation_id]
        value, citation = _project_field(field, requested, sources[context.source_id])
        item[field.field_name] = value
        if citation is not None:
            if citation not in item["source_refs"]:
                item["source_refs"].append(citation)
            if requested.kind == "population_count" and field.field_name == "count":
                item["count_source_ref"] = citation
                item["count_normalization"] = (
                    "integer_from_digit_string"
                    if field.normalization == "canonical_digit_string"
                    else "none"
                )
            elif requested.kind == "availability":
                item["available_source_ref"] = citation
            elif requested.kind == "endpoint" and field.field_name == "prespecification":
                item["prespecification_refs"] = [citation]
    for requested in scope.observations:
        if requested.endpoint_observation_id:
            count = observations[requested.observation_id]
            endpoint = observations[requested.endpoint_observation_id]
            endpoint["population_count_ids"].append(requested.observation_id)
            if count["group"] is not None and count["group"] not in endpoint["groups"]:
                endpoint["groups"].append(count["group"])
    trials = sorted({(item.trial_id, item.trial_family_id) for item in scope.contexts})
    dossier = {
        "schema_version": "clinical-dossier.v2",
        "intervention": "Not interpreted by deterministic extraction.",
        "indication": "Not interpreted by deterministic extraction.",
        "population": "Not interpreted by deterministic extraction; source-specific fields only.",
        "trials": [{"trial_id": trial, "trial_family_id": family} for trial, family in trials],
        "contexts": [
            {
                "context_id": item.context_id,
                "trial_id": item.trial_id,
                "source": _anchor(sources[item.source_id], item.source_path),
                "kind": item.kind,
                "label": "Public mechanical scope context: " + item.context_id,
                "analysis_id": item.analysis_id,
            }
            for item in scope.contexts
        ],
        "observations": list(observations.values()),
        "reconciliations": [],
        "claims": [],
        "contrary_evidence_claim_ids": [],
        "contrary_evidence_summary": "No search or clinical interpretation was performed.",
        "missing_inputs": [
            {
                "field": "Clinical interpretation and unscoped fields",
                "reason": "This baseline copies only public pointers "
                "under declared normalizations.",
                "consequence": "It cannot establish semantic support, "
                "clinical truth or completeness.",
            }
        ],
        "uncertainty": [
            "Deterministic public-input projection baseline; no private answer key or model used.",
            "Guided source copying is not source discovery or clinical research quality.",
            "No clinical claims, reconciliation judgment, efficacy conclusion or forecast is made.",
        ],
        "forecast": None,
    }
    try:
        bounded_json_size(dossier, MAX_DOSSIER_BYTES)
        return ClinicalDossierV2.model_validate(dossier)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ProjectionInputError("projection_output_contract_or_budget") from error
