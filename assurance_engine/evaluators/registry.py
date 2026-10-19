"""Native (deterministic) evaluators by check id."""

from __future__ import annotations

from .base import Evaluator
from .fitness import check_intended_use, check_origin
from .privacy.checks import check_destination, check_pii
from .quality.population import check_anomaly, check_duplicates, check_statistical
from .quality.relationship import check_relationship
from .quality.semantic import check_conflicts, check_semantic_rules
from .quality.structural import check_format, check_metadata, check_structural
from .quality.temporal import check_freshness, check_supersession
from .safety.injection import check_file, check_injection

__all__ = ["NATIVE_EVALUATORS"]

_E = Evaluator
NATIVE_EVALUATORS: dict[str, Evaluator] = {e.check_id: e for e in (
    _E("intake.format", "aidap.intake.format", check_format),
    _E("quality.structural", "aidap.quality.structural", check_structural),
    _E("quality.metadata", "aidap.quality.metadata", check_metadata),
    _E("quality.duplicates", "aidap.quality.duplicates", check_duplicates),
    _E("quality.statistical", "aidap.quality.statistical", check_statistical),
    _E("quality.anomaly", "aidap.quality.baseline_comparison", check_anomaly),
    _E("quality.relationship", "aidap.quality.relationships", check_relationship),
    _E("semantic.rules", "aidap.semantic.configured_rules", check_semantic_rules),
    _E("semantic.conflicts", "aidap.semantic.conflicts", check_conflicts),
    _E("temporal.freshness", "aidap.temporal.freshness", check_freshness),
    _E("temporal.supersession", "aidap.temporal.supersession", check_supersession),
    _E("fitness.intended_use", "aidap.fitness.intended_use", check_intended_use),
    _E("privacy.pii", "aidap.privacy.local_detectors", check_pii),
    _E("privacy.destination", "aidap.privacy.destination_rules", check_destination),
    _E("safety.file", "aidap.safety.file", check_file),
    _E("safety.injection", "aidap.safety.injection_patterns", check_injection),
    _E("provenance.origin", "aidap.provenance.metadata", check_origin),
)}
