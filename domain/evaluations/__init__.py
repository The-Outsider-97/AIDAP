"""Evaluation vocabulary and the check catalog."""

from .severity import Severity
from .confidence import Confidence, ConfidenceBasis, ConfidenceInterpretation
from .models import (Category, CheckResult, CheckSpec, CheckStatus, EvidencePointer, FailureClass,
                     Finding, Origin, UnknownReason)
from .quality import QUALITY_CHECKS
from .privacy import PRIVACY_CHECKS
from .safety import PROVENANCE_CHECKS, SAFETY_CHECKS, SLAI_CHECKS

CHECK_CATALOG: dict[str, CheckSpec] = {
    c.id: c for c in (*QUALITY_CHECKS, *PRIVACY_CHECKS, *SAFETY_CHECKS, *PROVENANCE_CHECKS, *SLAI_CHECKS)
}

__all__ = ["Severity", "Confidence", "ConfidenceBasis", "ConfidenceInterpretation", "Category",
           "CheckResult", "CheckSpec", "CheckStatus", "EvidencePointer", "FailureClass", "Finding",
           "Origin", "UnknownReason", "CHECK_CATALOG"]
