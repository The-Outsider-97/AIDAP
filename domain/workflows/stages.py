"""The 20-stage workflow of whitepaper Table 3."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["StageSpec", "STAGES", "STAGE_BY_NO", "EVALUATION_STAGES", "METERED_STAGES"]


@dataclass(frozen=True)
class StageSpec:
    no: int
    key: str
    title: str
    method: str          # D deterministic, S statistical, M model-assisted, H human
    meter: str | None = None   # billable meter derived from the stage record, idempotent per (run, meter)


STAGES: tuple[StageSpec, ...] = (
    StageSpec(1, "ingestion", "Ingestion", "D"),
    StageSpec(2, "normalization", "Normalization", "D"),
    StageSpec(3, "format_validation", "Format/schema validation", "D"),
    StageSpec(4, "structural_quality", "Structural quality", "D"),
    StageSpec(5, "statistical_quality", "Statistical quality", "D/S"),
    StageSpec(6, "anomaly_detection", "Anomaly detection", "S"),
    StageSpec(7, "relationship_analysis", "Relationship analysis", "D"),
    StageSpec(8, "semantic_fitness", "Semantic fitness", "D/M"),
    StageSpec(9, "privacy_screening", "Privacy screening", "D/M"),
    StageSpec(10, "safety_screening", "Safety screening", "D/M"),
    StageSpec(11, "provenance_evidence", "Provenance/evidence", "D"),
    StageSpec(12, "intended_use_fitness", "Intended-use fitness", "D/M"),
    StageSpec(13, "confidence", "Confidence", "S/M"),
    StageSpec(14, "policy_decision", "Policy decision", "D"),
    StageSpec(15, "disposition", "Disposition", "D/H"),
    StageSpec(16, "evidence_generation", "Evidence generation", "D"),
    StageSpec(17, "audit_logging", "Audit logging", "D"),
    StageSpec(18, "checkpointing", "Checkpointing", "D"),
    StageSpec(19, "alerting", "Alerting", "D"),
    StageSpec(20, "delivery", "Delivery", "D"),
)

STAGE_BY_NO = {s.no: s for s in STAGES}
EVALUATION_STAGES = tuple(range(2, 14))
METERED_STAGES = {14: "run"}   # one billable assurance run, recorded when the decision stage commits
