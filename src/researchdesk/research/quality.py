"""Pure structural/provenance checks and reference-based extraction scoring.

No network, model call, clock, store mutation or clinical efficacy judgment occurs
here. A matched quotation or JSON scalar proves its presence in a retained source,
not that the source is true or that it entails the associated claim.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .models import (
    ClinicalDossier,
    ClinicalExtraction,
    DossierCoverage,
    DossierValidationReport,
    ExtractionReference,
    ExtractionScore,
    FieldError,
    QualityCheck,
)
from .observation_models import ClinicalDossierV2

CLINICAL_DOSSIER_GUIDANCE = """Build a clinical-dossier.v2 evidence dossier.
Use inspect_source to navigate retained evidence by exact JSON pointer. Follow its
pagination; it returns raw values and source citations, not clinical interpretations.
Retain source/analysis contexts instead of merging all records into one trial-wide
answer. Distinguish original randomized assignment from a later external-control
analysis. Preserve enrolled, dosed, safety and endpoint populations separately.
Local group IDs are meaningful only within their exact owning source container;
for registry outcomes this is the individual outcome record, not the whole module.
Connect endpoint counts reciprocally to their endpoint. Do not sum populations
unless the source explicitly supports that operation.
Every present observation needs exact retained-source citations. Count citations
must identify the exact value: declare no normalization for integer/null values,
integer_from_digit_string for canonical count strings, or reported_in_text for
text extraction requiring independent review. Preserve source null separately from
false availability: a present availability flag needs its exact boolean/null
available_source_ref. Prose-based interpretations remain claims or unresolved.
Distinguish unresolved, not_applicable, and source_absent. source_absent requires an existing
parent object and the exact absent key; it does not mean evidence is absent from
the literature. A missing/invalid pointer is not proof of absence.
Citations require the artifact ID and full-content SHA-256, not a nested-source
hash. Quote complete canonical JSON scalars (405, false, null); text quotations
remain case-sensitive and whitespace-normalized. Use separate protocol/SAP
citations for prespecification; a current primary endpoint label is insufficient.
Reconcile differences with explicit retained observation IDs. Separate source-
reported explanations from your inferences, and state the inference basis.
Record contrary evidence, missing inputs, search limits and uncertainty. Passing
structural/citation checks does not prove clinical truth, semantic support,
efficacy, completeness or predictive skill.
For extraction-only work set forecast to null. If a forecast is requested, define
a falsifiable target, real as-of date, later horizon, outcome rule and resolution
source. Abstain explicitly when unsupported; never invent dates or probability.
Legacy clinical-dossier.v1 outputs remain readable but cannot express these source
and analysis distinctions.
"""

LIMITATIONS = [
    "Checks establish structure, source integrity and quotation/scalar presence, not claim truth "
    "or evidentiary support for an inference.",
    "A source labelled fact is a reported assertion, not an independently verified clinical fact.",
    "Completeness, prespecification, source availability at the cutoff and forecast quality "
    "require independent examination; no efficacy or confidence grade is produced.",
]

MAX_DOSSIER_BYTES = 200_000
MAX_DOSSIER_SOURCES = 30
MAX_SOURCE_CONTENT_BYTES = 8_000_000


class ResearchBudgetExceeded(ValueError):
    """Research input cannot be processed within its declared admission budget."""


def bounded_json_size(content: Any, limit: int) -> int:
    """Count canonical UTF-8 bytes, stopping before traversing excess content."""
    size = 0
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    for chunk in encoder.iterencode(content):
        size += len(chunk.encode())
        if size > limit:
            raise ResearchBudgetExceeded("Canonical JSON exceeds its byte budget.")
    return size


def check_dossier_budget(dossier: ClinicalDossier | ClinicalDossierV2) -> set[str]:
    if dossier.schema_version == "clinical-dossier.v2":
        from .observation_quality import check_observation_budget

        return check_observation_budget(dossier)
    bounded_json_size(dossier.model_dump(mode="json"), MAX_DOSSIER_BYTES)
    identifiers = {ref.artifact_id for claim in dossier.claims for ref in claim.source_refs}
    if len(identifiers) > MAX_DOSSIER_SOURCES:
        raise ResearchBudgetExceeded("A dossier may cite at most 30 distinct source artifacts.")
    return identifiers


def _budget_report(code: str, message: str) -> DossierValidationReport:
    return DossierValidationReport(
        valid=False,
        checks=[QualityCheck(code=code, path="/", passed=False, message=message)],
        coverage=DossierCoverage(),
        limitations=[
            *LIMITATIONS,
            "Validation stopped at an admission limit; checks are incomplete.",
        ],
    )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _hash(content: Any) -> str:
    # This is the canonical full-content encoding used by Store.content_hash.
    payload = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _scalar_excerpt(value: Any) -> str:
    """Encode a non-text JSON scalar using the artifact hash's JSON convention.

    This is the complete parsed value, not a substring, coercion, original JSON
    numeric lexeme or clinical interpretation. Integers and floats retain their
    serializer spelling (1 differs from 1.0); booleans/null are lowercase. NaN and
    infinity are rejected. Text uses the existing quotation path instead.
    """
    if value is not None and type(value) not in (bool, int, float):
        raise ValueError("A scalar citation must select a JSON scalar.")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _pointer(content: Any, pointer: str) -> Any:
    if pointer == "":
        return content
    if not pointer.startswith("/"):
        raise ValueError("Source path must be an RFC 6901 JSON pointer.")
    current = content
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw):
            raise ValueError("Invalid JSON pointer escape.")
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[key]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9]\d*", key):
            current = current[int(key)]
        else:
            raise ValueError("Source path does not resolve within the content.")
    return current


def _schema_checks(error: ValidationError, prefix: str = "") -> list[QualityCheck]:
    return [
        QualityCheck(
            code=f"schema.{item['type']}",
            path=prefix + "/" + "/".join(str(part) for part in item["loc"]),
            passed=False,
            message=item["msg"],
        )
        for item in error.errors(include_input=False, include_url=False)
    ]


class CitationValidator:
    """Shared source-presence checks for bounded dossier validators.

    Callers enforce their dossier/source byte and count admission limits first.
    A fresh instance belongs to one validation; caches never cross source sets.
    Presence and identity do not establish that a claim follows from the source.
    """

    def __init__(self, artifacts: Mapping[str, dict], invalid_sources=()):
        self.artifacts = artifacts
        self.invalid_sources = frozenset(invalid_sources)
        self.hashes: dict[str, str | None] = {}
        self.normalized: dict[tuple[str, str | None], tuple[str | None, tuple[str, ...]]] = {}

    def identity(self, source, path: str) -> list[QualityCheck]:
        checks: list[QualityCheck] = []

        def check(code, path, passed, message):
            checks.append(QualityCheck(code=code, path=path, passed=passed, message=message))
            return passed

        artifact = self.artifacts.get(source.artifact_id)
        if not check(
            "source_exists",
            path,
            isinstance(artifact, Mapping),
            "The referenced evidence artifact must be supplied.",
        ):
            return checks
        check(
            "source_identity",
            path,
            artifact.get("id") == source.artifact_id,
            "The artifact's stored identity must match the reference.",
        )
        check(
            "source_kind",
            path,
            artifact.get("kind") == "evidence",
            "A dossier source must be an evidence artifact.",
        )
        if source.artifact_id not in self.hashes:
            try:
                self.hashes[source.artifact_id] = (
                    None
                    if source.artifact_id in self.invalid_sources
                    else _hash(artifact["content"])
                )
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
                self.hashes[source.artifact_id] = None
        actual_hash = self.hashes[source.artifact_id]
        check(
            "source_content_integrity",
            path,
            actual_hash is not None and artifact.get("sha256") == actual_hash,
            "The stored hash must match the complete canonical artifact content.",
        )
        check(
            "source_version_match",
            path,
            actual_hash is not None and source.artifact_sha256 == actual_hash,
            "The citation hash must identify this exact complete artifact content.",
        )
        return checks

    def anchor(self, source, path: str) -> list[QualityCheck]:
        """Verify an exact source location; containers are valid context anchors.

        An anchor identifies retained data only. It does not certify a group
        mapping, an analysis interpretation or an assertion of missing evidence.
        """
        checks = self.identity(source, path)
        resolved = False
        if all(check.passed for check in checks):
            try:
                _pointer(self.artifacts[source.artifact_id]["content"], source.source_path)
                resolved = True
            except (KeyError, ValueError, IndexError, TypeError, AttributeError):
                pass
        checks.append(
            QualityCheck(
                code="source_anchor_exists",
                path=path + "/source_path",
                passed=resolved,
                message="The exact source version must contain the anchored JSON location.",
            )
        )
        return checks

    def validate(self, source, path: str) -> list[QualityCheck]:
        checks = self.identity(source, path)
        if not checks[0].passed:
            return checks

        def check(code, path, passed, message):
            checks.append(QualityCheck(code=code, path=path, passed=passed, message=message))
            return passed

        artifact = self.artifacts[source.artifact_id]
        actual_hash = self.hashes.get(source.artifact_id)
        # Invalid/non-JSON content cannot be searched as trusted retained text.
        content = artifact.get("content") if actual_hash is not None else None
        cache_key = (source.artifact_id, source.source_path)
        if cache_key not in self.normalized:
            if source.source_path is not None:
                selection_kind, excerpts = None, ()
                try:
                    if actual_hash is None:
                        raise ValueError("The source content is not valid JSON.")
                    selected = _pointer(content, source.source_path)
                    if isinstance(selected, str):
                        selection_kind, excerpts = "text", (_normalize(selected),)
                    else:
                        excerpts = (_scalar_excerpt(selected),)
                        selection_kind = "scalar"
                except (KeyError, ValueError, IndexError, TypeError, OverflowError):
                    pass
            else:
                selection_kind = "search"
                excerpts = tuple(_normalize(text) for text in _strings(content))
            self.normalized[cache_key] = (selection_kind, excerpts)
        selection_kind, strings = self.normalized[cache_key]
        if source.source_path is not None:
            check(
                "source_path_is_scalar",
                path + "/source_path",
                selection_kind in ("text", "scalar"),
                "The JSON pointer must resolve to a string, finite number, boolean or null; "
                "missing values, objects and arrays do not qualify.",
            )
        excerpt = _normalize(source.excerpt)
        present = (
            excerpt in strings
            if selection_kind == "scalar"
            else any(excerpt in text for text in strings)
        )
        check(
            "quote_present",
            path + "/excerpt",
            bool(excerpt) and present,
            "The whitespace-normalized, case-sensitive excerpt must occur within "
            "one source string, or exactly equal the complete canonical JSON value of "
            "a pointer-selected finite number, boolean or null. Serialized containers "
            "and joined fields do not count.",
        )
        return checks


def validate_dossier(
    dossier: ClinicalDossier | ClinicalDossierV2 | dict, artifacts_by_id: Mapping[str, dict]
) -> DossierValidationReport:
    """Validate a dossier without altering it or the supplied retained artifacts."""
    from . import parse_dossier

    try:
        parsed = parse_dossier(dossier)
    except ValidationError as error:
        return DossierValidationReport(
            valid=False,
            checks=_schema_checks(error),
            coverage=DossierCoverage(),
            limitations=LIMITATIONS,
        )
    if isinstance(parsed, ClinicalDossierV2):
        from .observation_quality import validate_observation_dossier

        return validate_observation_dossier(parsed, artifacts_by_id)
    try:
        identifiers = check_dossier_budget(parsed)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return _budget_report(
            "dossier_budget",
            "Dossier must fit 200 KB and cite at most 30 distinct source artifacts.",
        )
    source_bytes = 0
    invalid_sources: set[str] = set()
    for identifier in sorted(identifiers):
        artifact = artifacts_by_id.get(identifier)
        if not isinstance(artifact, Mapping):
            continue
        try:
            source_bytes += bounded_json_size(
                artifact["content"], MAX_SOURCE_CONTENT_BYTES - source_bytes
            )
        except ResearchBudgetExceeded:
            return _budget_report(
                "source_budget", "Combined source artifact content must fit 8 MB."
            )
        except ValueError:
            invalid_sources.add(identifier)
        except (TypeError, KeyError, OverflowError, RecursionError):
            invalid_sources.add(identifier)
    citations = CitationValidator(artifacts_by_id, invalid_sources)
    checks: list[QualityCheck] = []

    def check(code: str, path: str, passed: bool, message: str) -> bool:
        checks.append(QualityCheck(code=code, path=path, passed=passed, message=message))
        return passed

    check("schema_valid", "/", True, "The dossier matches the clinical output contract.")
    claim_counts = Counter(claim.id for claim in parsed.claims)
    trial_counts = Counter(trial.trial_id for trial in parsed.trials)
    for kind, counts in (("claim", claim_counts), ("trial", trial_counts)):
        check(
            f"unique_{kind}_ids",
            f"/{kind}s",
            all(n == 1 for n in counts.values()),
            f"Every {kind} identifier must be unique.",
        )
    claims = {claim.id: claim for claim in parsed.claims}
    used_claims: set[str] = set()

    def claim_links(ids: list[str], path: str, trial_id: str | None = None):
        for index, identifier in enumerate(ids):
            target = f"{path}/{index}"
            exists = claim_counts[identifier] == 1
            check(
                "claim_reference_exists",
                target,
                exists,
                "A claim reference must identify exactly one dossier claim.",
            )
            if exists:
                used_claims.add(identifier)
                if trial_id is not None:
                    check(
                        "claim_trial_binding",
                        target,
                        trial_id in claims[identifier].trial_ids,
                        "A trial's supporting claim must name that trial.",
                    )

    for ti, trial in enumerate(parsed.trials):
        path = f"/trials/{ti}"
        claim_links(trial.source_claim_ids, path + "/source_claim_ids", trial.trial_id)
        for collection, id_field in (("arms", "arm_id"), ("endpoints", "endpoint_id")):
            records = getattr(trial, collection)
            ids = [getattr(record, id_field) for record in records]
            check(
                f"unique_{collection}_ids",
                path + f"/{collection}",
                len(ids) == len(set(ids)),
                "Identifiers must be unique within the trial.",
            )
            for ri, record in enumerate(records):
                claim_links(
                    record.source_claim_ids,
                    f"{path}/{collection}/{ri}/source_claim_ids",
                    trial.trial_id,
                )
    claim_links(parsed.contrary_evidence_claim_ids, "/contrary_evidence_claim_ids")
    verified_references = 0
    fully_attributed = 0
    sources: set[str] = set()
    for ci, claim in enumerate(parsed.claims):
        claim_path = f"/claims/{ci}"
        check(
            "claim_not_orphaned",
            claim_path,
            claim.id in used_claims,
            "Every claim must support a trial field or be identified as contrary evidence.",
        )
        for ti, trial_id in enumerate(claim.trial_ids):
            check(
                "trial_reference_exists",
                f"{claim_path}/trial_ids/{ti}",
                trial_counts[trial_id] == 1,
                "A claim's trial reference must identify exactly one dossier trial.",
            )
        if claim.kind == "inference":
            check(
                "inference_basis_required",
                claim_path + "/inference_basis",
                bool(claim.inference_basis),
                "Inferences must explain the reasoning beyond the quoted source.",
            )
        claim_verified = True
        for si, source in enumerate(claim.source_refs):
            path = f"{claim_path}/source_refs/{si}"
            start = len(checks)
            checks.extend(citations.validate(source, path))
            reference_verified = all(item.passed for item in checks[start:])
            verified_references += int(reference_verified)
            claim_verified &= reference_verified
            if reference_verified:
                sources.add(source.artifact_id)
        fully_attributed += int(claim_verified)
    forecast = parsed.forecast
    check(
        "forecast_horizon",
        "/forecast/horizon",
        forecast.horizon > forecast.as_of,
        "The outcome horizon must follow the stated information cutoff.",
    )
    if forecast.status == "abstain":
        check(
            "abstention_reason_required",
            "/forecast/abstention_reason",
            bool(forecast.abstention_reason),
            "Abstention requires an explicit reason.",
        )
        check(
            "abstention_has_no_prediction",
            "/forecast",
            forecast.prediction is None and forecast.probability is None,
            "An abstention cannot simultaneously assert a prediction or probability.",
        )
    else:
        check(
            "forecast_prediction_required",
            "/forecast/prediction",
            bool(forecast.prediction),
            "A forecast requires an explicit falsifiable prediction.",
        )
        check(
            "forecast_has_no_abstention",
            "/forecast/abstention_reason",
            forecast.abstention_reason is None,
            "A forecast cannot simultaneously declare an abstention.",
        )
    return DossierValidationReport(
        valid=all(item.passed for item in checks),
        checks=checks,
        coverage=DossierCoverage(
            trials=len(parsed.trials),
            claims=len(parsed.claims),
            facts=sum(c.kind == "fact" for c in parsed.claims),
            inferences=sum(c.kind == "inference" for c in parsed.claims),
            source_references=sum(len(c.source_refs) for c in parsed.claims),
            verified_source_references=verified_references,
            fully_attributed_claims=fully_attributed,
            distinct_sources=len(sources),
            contrary_claims=len(set(parsed.contrary_evidence_claim_ids)),
            missing_inputs=len(parsed.missing_inputs),
        ),
        limitations=LIMITATIONS,
    )


def _extraction(candidate: ClinicalDossier | ClinicalExtraction | dict) -> ClinicalExtraction:
    if isinstance(candidate, ClinicalDossier) or (
        isinstance(candidate, dict) and candidate.get("schema_version") == "clinical-dossier.v1"
    ):
        raw = candidate.model_dump() if isinstance(candidate, ClinicalDossier) else candidate
        projection = {name: raw.get(name) for name in ("intervention", "indication", "population")}
        projection["trials"] = []
        for trial in raw.get("trials", []):
            record = {name: trial.get(name) for name in ("trial_id", "design")}
            for collection in ("arms", "endpoints"):
                record[collection] = [
                    {key: value for key, value in item.items() if key != "source_claim_ids"}
                    for item in trial.get(collection, [])
                ]
            projection["trials"].append(record)
        return ClinicalExtraction.model_validate(projection)
    return ClinicalExtraction.model_validate(
        candidate.model_dump() if isinstance(candidate, ClinicalExtraction) else candidate
    )


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _flatten(record: ClinicalExtraction) -> tuple[dict, list[QualityCheck]]:
    fields: dict[str, str | int | bool] = {}
    errors: list[QualityCheck] = []

    def add(path, value):
        if value is not None and (not isinstance(value, str) or _normalize(value)):
            fields[path] = _normalize(value).casefold() if isinstance(value, str) else value

    for field in ("intervention", "indication", "population"):
        add("/" + field, getattr(record, field))
    seen_trials: set[str] = set()
    for trial in record.trials:
        identifier = _normalize(trial.trial_id).casefold()
        path = "/trials/" + _escape(identifier)
        if identifier in seen_trials:
            errors.append(
                QualityCheck(
                    code="duplicate_trial_id",
                    path=path,
                    passed=False,
                    message="Duplicate identifiers cannot be aligned for scoring.",
                )
            )
        seen_trials.add(identifier)
        add(path + "/trial_id", trial.trial_id)
        for field, value in trial.design.model_dump().items():
            add(f"{path}/design/{field}", value)
        for collection, key in (("arms", "arm_id"), ("endpoints", "endpoint_id")):
            seen: set[str] = set()
            for item in getattr(trial, collection):
                identifier = _normalize(getattr(item, key)).casefold()
                item_path = f"{path}/{collection}/{_escape(identifier)}"
                if identifier in seen:
                    errors.append(
                        QualityCheck(
                            code=f"duplicate_{key}",
                            path=item_path,
                            passed=False,
                            message="Duplicate identifiers cannot be aligned for scoring.",
                        )
                    )
                seen.add(identifier)
                for field, value in item.model_dump().items():
                    add(f"{item_path}/{field}", value)
    return fields, errors


def score_extraction(
    candidate: ClinicalDossier | ClinicalExtraction | dict,
    reference: ExtractionReference | dict,
) -> ExtractionScore:
    """Compare declared trial facts against a complete, independently curated reference.

    A wrong value counts once as a false positive and once as a false negative.
    Extra candidate facts count as false positives; omissions as false negatives.
    Undefined denominators return None. Text comparison folds case/whitespace only:
    no semantic equivalence, drug alias or numerical-unit conversion is inferred.
    """
    limitations = [
        "Scores measure agreement with this reference, not clinical truth, "
        "efficacy or calibration.",
        "Reference coverage must be complete for the declared extraction schema; omitted "
        "reference values are treated as unsupported candidate assertions.",
        "Comparison normalizes Unicode, case and whitespace only; equivalent wording or units "
        "may require human adjudication. Claims, quotations and forecasts are outside this score.",
    ]
    errors: list[QualityCheck] = []
    expected: dict = {}
    actual: dict = {}
    reference_id = "unvalidated"
    try:
        parsed_reference = ExtractionReference.model_validate(
            reference.model_dump() if isinstance(reference, ExtractionReference) else reference
        )
        reference_id = parsed_reference.reference_id
        expected, duplicate_errors = _flatten(parsed_reference.extraction)
        errors.extend(
            item.model_copy(update={"path": "/reference" + item.path}) for item in duplicate_errors
        )
        if not expected:
            errors.append(
                QualityCheck(
                    code="empty_reference",
                    path="/reference",
                    passed=False,
                    message="An empty reference cannot yield a quality score.",
                )
            )
    except ValidationError as error:
        errors.extend(_schema_checks(error, "/reference"))
    try:
        actual, duplicate_errors = _flatten(_extraction(candidate))
        errors.extend(
            item.model_copy(update={"path": "/candidate" + item.path}) for item in duplicate_errors
        )
    except (ValidationError, TypeError, AttributeError) as error:
        if isinstance(error, ValidationError):
            errors.extend(_schema_checks(error, "/candidate"))
        else:
            errors.append(
                QualityCheck(
                    code="invalid_candidate",
                    path="/candidate",
                    passed=False,
                    message="Candidate extraction structure is invalid.",
                )
            )
    field_errors = []
    tp = fp = fn = 0
    if not errors:
        for path in sorted(set(expected) | set(actual)):
            if path in expected and path in actual and expected[path] == actual[path]:
                tp += 1
                continue
            code = (
                "unexpected_field"
                if path not in expected
                else "missing_field"
                if path not in actual
                else "value_mismatch"
            )
            fp += int(path in actual)
            fn += int(path in expected)
            field_errors.append(
                FieldError(
                    path=path,
                    code=code,
                    expected=expected.get(path),
                    actual=actual.get(path),
                    critical=path.rsplit("/", 1)[-1] != "label",
                )
            )
    precision = tp / (tp + fp) if not errors and tp + fp else None
    recall = tp / (tp + fn) if not errors and tp + fn else None
    f1 = (2 * tp / (2 * tp + fp + fn)) if not errors and 2 * tp + fp + fn else None
    return ExtractionScore(
        reference_id=reference_id,
        valid=not errors,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        reference_fields=len(expected),
        candidate_fields=len(actual),
        errors=field_errors,
        critical_errors=[error for error in field_errors if error.critical],
        schema_errors=errors,
        limitations=limitations,
    )
