"""Typed, source-attributed clinical research and deterministic extraction checks."""

from collections.abc import Mapping

from .models import (
    ClinicalDossier,
    ClinicalExtraction,
    DossierValidationReport,
    ExtractionReference,
    ExtractionScore,
)
from .observation_models import ClinicalDossierV2
from .quality import CLINICAL_DOSSIER_GUIDANCE, score_extraction, validate_dossier


def parse_dossier(value) -> ClinicalDossierV2 | ClinicalDossier:
    """Read both immutable output versions without flattening their meaning."""
    if isinstance(value, ClinicalDossierV2) or (
        isinstance(value, Mapping) and value.get("schema_version") == "clinical-dossier.v2"
    ):
        return ClinicalDossierV2.model_validate(value)
    # Missing versions retain the historical v1 interpretation. Select one schema
    # before validation so failure paths remain exact JSON paths, not union labels.
    return ClinicalDossier.model_validate(value)


__all__ = [
    "CLINICAL_DOSSIER_GUIDANCE",
    "ClinicalDossier",
    "ClinicalDossierV2",
    "ClinicalExtraction",
    "DossierValidationReport",
    "ExtractionReference",
    "ExtractionScore",
    "score_extraction",
    "validate_dossier",
    "parse_dossier",
]
