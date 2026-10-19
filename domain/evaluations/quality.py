"""Quality, semantic, temporal and fitness checks in the AIDAP catalog."""

from __future__ import annotations

from .models import Category, CheckSpec, FailureClass, Origin

__all__ = ["QUALITY_CHECKS"]

_Q = Category.QUALITY

QUALITY_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("intake.format", Category.INTAKE, 3, "Format and parse coverage", "D",
              "The input is a supported format, parses completely and within limits.",
              FailureClass.STRUCTURAL, default_mandatory=True),
    CheckSpec("quality.structural", _Q, 4, "Structural integrity", "D",
              "Required fields, types, ranges and domains declared by the intended-use profile.",
              FailureClass.STRUCTURAL, default_mandatory=True),
    CheckSpec("quality.metadata", _Q, 4, "Required metadata", "D",
              "Metadata that the profile requires (owner, source revision, effective date...).",
              FailureClass.PROVENANCE, default_mandatory=True),
    CheckSpec("quality.duplicates", _Q, 5, "Duplicates", "D",
              "Exact and near-exact duplicate records or passages.", FailureClass.POPULATION),
    CheckSpec("quality.statistical", _Q, 5, "Missingness and sample coverage", "S",
              "Missingness, constant columns and sample sufficiency.", FailureClass.POPULATION),
    CheckSpec("quality.anomaly", _Q, 6, "Distribution comparison", "S",
              "Numeric and categorical comparison with an *approved* baseline only.",
              FailureClass.POPULATION, needs_baseline=True),
    CheckSpec("quality.relationship", _Q, 7, "Cross-field relationships", "D",
              "Configured cross-field dependencies and reference keys.", FailureClass.STRUCTURAL),
    CheckSpec("semantic.rules", Category.SEMANTIC, 8, "Configured semantic rules", "D",
              "Profile-configured meaning rules, forbidden/required phrases and label leakage.",
              FailureClass.SEMANTIC),
    CheckSpec("semantic.conflicts", Category.SEMANTIC, 8, "Conflicting statements", "D",
              "Conflicting values for the same key within the input, with both spans cited.",
              FailureClass.SEMANTIC),
    CheckSpec("temporal.freshness", Category.TEMPORAL, 8, "Freshness window", "D",
              "Effective/expiry dates and the profile freshness window.", FailureClass.TEMPORAL,
              default_mandatory=True),
    CheckSpec("temporal.supersession", Category.TEMPORAL, 8, "Superseded content", "D",
              "Revision relationships: is this input superseded by a newer approved version.",
              FailureClass.TEMPORAL),
    CheckSpec("fitness.intended_use", Category.FITNESS, 12, "Intended-use fitness", "D",
              "Source class, audience, classification and destination against the profile.",
              FailureClass.CONTEXTUAL, default_mandatory=True),
)
