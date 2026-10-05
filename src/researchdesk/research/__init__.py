"""Typed, source-attributed clinical research and deterministic extraction checks."""

from .models import (
    ClinicalDossier,
    ClinicalExtraction,
    DossierValidationReport,
    ExtractionReference,
    ExtractionScore,
)
from .quality import CLINICAL_DOSSIER_GUIDANCE, score_extraction, validate_dossier

__all__ = [
    "CLINICAL_DOSSIER_GUIDANCE",
    "ClinicalDossier",
    "ClinicalExtraction",
    "DossierValidationReport",
    "ExtractionReference",
    "ExtractionScore",
    "score_extraction",
    "validate_dossier",
]
