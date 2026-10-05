"""Structural/source checks for source-qualified clinical observations.

These checks cannot establish clinical truth, semantic entailment or the validity
of a comparison. They preserve source and analysis boundaries for later review.
"""

import re
from collections import Counter
from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from .models import DossierCoverage, DossierValidationReport, QualityCheck, SourceReference
from .observation_models import ClinicalDossierV2, MissingKeyProof, SourceAnchor
from .quality import (
    LIMITATIONS,
    MAX_DOSSIER_BYTES,
    MAX_DOSSIER_SOURCES,
    MAX_SOURCE_CONTENT_BYTES,
    CitationValidator,
    ResearchBudgetExceeded,
    _budget_report,
    _pointer,
    _schema_checks,
    bounded_json_size,
)


def walk(value, path=""):
    """Visit typed values without flattening source contexts or field states."""
    yield value, path
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from walk(getattr(value, name), path + "/" + name)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk(item, path + f"/{index}")


def source_bindings(dossier):
    return [
        (item, path)
        for item, path in walk(dossier)
        if isinstance(item, (SourceAnchor, SourceReference))
    ]


def check_observation_budget(dossier):
    bounded_json_size(dossier.model_dump(mode="json"), MAX_DOSSIER_BYTES)
    identifiers = {item.artifact_id for item, _ in source_bindings(dossier)}
    if len(identifiers) > MAX_DOSSIER_SOURCES:
        raise ResearchBudgetExceeded("A dossier may cite at most 30 distinct source artifacts")
    return identifiers


def _within(reference, context):
    """Compare exact JSON-pointer boundaries, never ambiguous text prefixes."""
    base, selected = context.source_path, reference.source_path
    return (
        reference.artifact_id == context.artifact_id
        and reference.artifact_sha256 == context.artifact_sha256
        and selected is not None
        and (base == "" or selected == base or selected.startswith(base + "/"))
    )


def validate_observation_dossier(dossier, artifacts_by_id: Mapping[str, dict]):
    try:
        parsed = ClinicalDossierV2.model_validate(
            dossier.model_dump() if isinstance(dossier, ClinicalDossierV2) else dossier
        )
    except ValidationError as error:
        return DossierValidationReport(
            valid=False,
            checks=_schema_checks(error),
            coverage=DossierCoverage(),
            limitations=LIMITATIONS,
        )
    try:
        identifiers = check_observation_budget(parsed)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return _budget_report(
            "dossier_budget", "Dossier must fit 200 KB and cite at most 30 sources"
        )
    invalid_sources, source_bytes = set(), 0
    for identifier in sorted(identifiers):
        artifact = artifacts_by_id.get(identifier)
        if not isinstance(artifact, Mapping):
            continue
        try:
            source_bytes += bounded_json_size(
                artifact["content"], MAX_SOURCE_CONTENT_BYTES - source_bytes
            )
        except ResearchBudgetExceeded:
            return _budget_report("source_budget", "Combined source content must fit 8 MB")
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            invalid_sources.add(identifier)
    citations = CitationValidator(artifacts_by_id, invalid_sources)
    checks = []

    def check(code, path, passed, message):
        checks.append(QualityCheck(code=code, path=path, passed=bool(passed), message=message))
        return bool(passed)

    check("schema_valid", "/", True, "The dossier matches the source-qualified output contract")
    references = {}
    for binding, path in source_bindings(parsed):
        result = (
            citations.validate(binding, path)
            if isinstance(binding, SourceReference)
            else citations.anchor(binding, path)
        )
        checks.extend(result)
        references[path] = all(item.passed for item in result)
    for item, path in walk(parsed):
        if not isinstance(item, MissingKeyProof):
            continue
        absent = False
        if references.get(path + "/parent"):
            try:
                parent = _pointer(
                    artifacts_by_id[item.parent.artifact_id]["content"], item.parent.source_path
                )
                absent = isinstance(parent, dict) and item.key not in parent
            except (KeyError, ValueError, TypeError, IndexError):
                pass
        check(
            "source_key_absent",
            path,
            absent,
            "Absence means this exact key is absent from an existing JSON object; "
            "it is not absence of clinical evidence",
        )

    collections = (
        ("trial", parsed.trials, "trial_id"),
        ("context", parsed.contexts, "context_id"),
        ("observation", parsed.observations, "observation_id"),
        ("claim", parsed.claims, "id"),
    )
    counts, indexed = {}, {}
    for name, values, field in collections:
        counts[name] = Counter(getattr(item, field) for item in values)
        indexed[name] = {getattr(item, field): item for item in values}
        check(
            f"unique_{name}_ids",
            f"/{name}s",
            all(n == 1 for n in counts[name].values()),
            f"Every {name} must have a distinct identifier",
        )

    def link(kind, identifier, path):
        return check(
            f"{kind}_reference_exists",
            path,
            counts[kind][identifier] == 1,
            f"Reference must identify exactly one {kind}",
        )

    for index, context in enumerate(parsed.contexts):
        link("trial", context.trial_id, f"/contexts/{index}/trial_id")

    fully_attributed_observations = 0
    for index, observation in enumerate(parsed.observations):
        path = f"/observations/{index}"
        context_valid = link("context", observation.context_id, path + "/context_id")
        context = indexed["context"].get(observation.context_id) if context_valid else None
        if context:
            for binding, relative in source_bindings(observation):
                # Prespecification may need a different protocol/SAP source. Its
                # dedicated citations remain checked, but are not forced into the
                # publication/registry container whose endpoint is being described.
                if relative.startswith(("/prespecification_refs/", "/prespecification/proof/")):
                    continue
                check(
                    "observation_source_context",
                    path + relative,
                    _within(binding, context.source),
                    "A reported observation must retain its exact source version "
                    "and container context",
                )
        if observation.kind == "population_count" and observation.count.state == "present":
            ref = observation.count_source_ref
            matched = False
            if references.get(path + "/count_source_ref") and ref.source_path is not None:
                raw = _pointer(artifacts_by_id[ref.artifact_id]["content"], ref.source_path)
                value = observation.count.value
                match observation.count_normalization:
                    case "none":
                        matched = (raw is None and value is None) or (
                            type(raw) is int and raw == value
                        )
                    case "integer_from_digit_string":
                        matched = (
                            isinstance(raw, str)
                            and re.fullmatch(r"0|[1-9][0-9]*", raw) is not None
                            and raw == str(value)
                        )
                    case "reported_in_text":
                        matched = isinstance(raw, str)
            check(
                "count_value_matches_source",
                path + "/count",
                matched,
                "Counts must preserve an exact integer/null, explicitly normalize a canonical "
                "digit string, or declare extraction from cited text. Text extraction still "
                "requires independent semantic review; quotation presence does not verify "
                "the count.",
            )
        if observation.kind == "availability" and observation.available.state == "present":
            ref = observation.available_source_ref
            matched = False
            if references.get(path + "/available_source_ref") and ref.source_path is not None:
                raw = _pointer(artifacts_by_id[ref.artifact_id]["content"], ref.source_path)
                matched = type(raw) is type(observation.available.value) and (
                    raw == observation.available.value
                )
            check(
                "available_value_matches_source",
                path + "/available",
                matched,
                "Reported availability must preserve an exact source boolean or null. "
                "Null, missing keys, zero and text do not establish false availability.",
            )
        groups = (
            [observation.group] if getattr(observation, "group", None) is not None else []
        ) + list(getattr(observation, "groups", []))
        for group_index, group in enumerate(groups):
            group_path = path + f"/group_locations/{group_index}"
            check(
                "group_context_identity",
                group_path,
                context is not None and group.container == context.source,
                "The observation context must identify the exact container owning this local "
                "group ID, not a broader root or another outcome",
            )
            matches = 0
            if all(check.passed for check in citations.anchor(group.container, group_path)):
                value = _pointer(
                    artifacts_by_id[group.container.artifact_id]["content"],
                    group.container.source_path,
                )
                raw_groups = value.get("groups", []) if isinstance(value, dict) else []
                if isinstance(raw_groups, list):
                    matches = sum(
                        isinstance(item, dict) and item.get("id") == group.local_id
                        for item in raw_groups
                    )
            check(
                "group_local_identity",
                group_path,
                matches == 1,
                "A local group ID must occur exactly once in this source container's groups array",
            )
        if observation.kind == "population_count" and observation.endpoint_observation_id:
            target = observation.endpoint_observation_id
            if link("observation", target, path + "/endpoint_observation_id"):
                endpoint = indexed["observation"][target]
                check(
                    "population_endpoint_context",
                    path,
                    endpoint.kind == "endpoint"
                    and endpoint.context_id == observation.context_id
                    and observation.observation_id in endpoint.population_count_ids,
                    "Endpoint denominators must name an endpoint in the same analysis context "
                    "that reciprocally includes this count",
                )
        if observation.kind == "endpoint":
            for count_index, identifier in enumerate(observation.population_count_ids):
                target_path = path + f"/population_count_ids/{count_index}"
                if link("observation", identifier, target_path):
                    count = indexed["observation"][identifier]
                    check(
                        "endpoint_population_context",
                        target_path,
                        count.kind == "population_count"
                        and count.context_id == observation.context_id
                        and count.endpoint_observation_id == observation.observation_id,
                        "An endpoint denominator must explicitly identify this endpoint "
                        "and context",
                    )
        binding_paths = [path + relative for _, relative in source_bindings(observation)]
        fully_attributed_observations += int(
            bool(observation.source_refs)
            and all(references.get(p) for p in binding_paths)
            and all(
                item.passed
                for item in checks
                if item.path == path or item.path.startswith(path + "/")
            )
            and context is not None
            and all(item.passed for item in citations.anchor(context.source, path))
        )

    for index, reconciliation in enumerate(parsed.reconciliations):
        path = f"/reconciliations/{index}"
        for target_index, identifier in enumerate(reconciliation.observation_ids):
            link("observation", identifier, path + f"/observation_ids/{target_index}")
        check(
            "reconciliation_distinct_observations",
            path,
            len(set(reconciliation.observation_ids)) == len(reconciliation.observation_ids),
            "Reconciliation must link distinct retained observations",
        )
        if reconciliation.kind == "inference":
            check(
                "inference_basis",
                path + "/inference_basis",
                bool(reconciliation.inference_basis),
                "An inferred reconciliation must explain reasoning beyond the source",
            )

    fully_attributed_claims = 0
    for index, claim in enumerate(parsed.claims):
        path = f"/claims/{index}"
        for trial_index, identifier in enumerate(claim.trial_ids):
            link("trial", identifier, path + f"/trial_ids/{trial_index}")
        if claim.kind == "inference":
            check(
                "inference_basis",
                path + "/inference_basis",
                bool(claim.inference_basis),
                "Inferences must explain reasoning beyond the source",
            )
        fully_attributed_claims += int(
            all(references.get(path + f"/source_refs/{i}") for i in range(len(claim.source_refs)))
        )
    for index, identifier in enumerate(parsed.contrary_evidence_claim_ids):
        link("claim", identifier, f"/contrary_evidence_claim_ids/{index}")

    forecast = parsed.forecast
    if forecast is not None:
        check(
            "forecast_horizon",
            "/forecast/horizon",
            forecast.horizon > forecast.as_of,
            "The outcome horizon must follow the stated information cutoff",
        )
        if forecast.status == "abstain":
            check(
                "abstention_reason_required",
                "/forecast",
                bool(forecast.abstention_reason),
                "Abstention requires an explicit reason",
            )
            check(
                "abstention_has_no_prediction",
                "/forecast",
                forecast.prediction is None and forecast.probability is None,
                "Abstention cannot also assert a prediction or probability",
            )
        else:
            check(
                "forecast_prediction_required",
                "/forecast",
                bool(forecast.prediction),
                "A forecast requires a falsifiable prediction",
            )
            check(
                "forecast_has_no_abstention",
                "/forecast",
                forecast.abstention_reason is None,
                "A forecast cannot also declare abstention",
            )
    refs = [
        (value, path)
        for value, path in source_bindings(parsed)
        if isinstance(value, SourceReference)
    ]
    return DossierValidationReport(
        valid=all(item.passed for item in checks),
        checks=checks,
        coverage=DossierCoverage(
            trials=len(parsed.trials),
            contexts=len(parsed.contexts),
            observations=len(parsed.observations),
            reconciliations=len(parsed.reconciliations),
            fully_attributed_observations=fully_attributed_observations,
            claims=len(parsed.claims),
            facts=sum(c.kind == "fact" for c in parsed.claims),
            inferences=sum(c.kind == "inference" for c in parsed.claims),
            source_references=len(refs),
            verified_source_references=sum(references[path] for _, path in refs),
            fully_attributed_claims=fully_attributed_claims,
            distinct_sources=len({value.artifact_id for value, path in refs if references[path]}),
            contrary_claims=len(set(parsed.contrary_evidence_claim_ids)),
            missing_inputs=len(parsed.missing_inputs),
        ),
        limitations=[
            *LIMITATIONS,
            "Container/group identity does not prove that an observation interprets its source "
            "correctly. Missing-key checks establish only literal absence at that location. "
            "No clinical reference score is computed.",
        ],
    )
