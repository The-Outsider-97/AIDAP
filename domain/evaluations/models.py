"""Evaluation records: findings, check results and the check catalog entry type.

A finding separates *observed evidence*, *detector inference*, *confidence
interpretation*, *severity* and *recommended action* (whitepaper 7.3.1).
A check that did not run is ``UNKNOWN`` / ``NOT_EVALUATED`` / ``ERROR`` and
is never reported as a perfect score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .confidence import Confidence
from .severity import Severity

__all__ = ["CheckStatus", "UnknownReason", "FailureClass", "Origin", "Category",
           "CheckSpec", "Finding", "CheckResult", "EvidencePointer"]


class Category(str, Enum):
    INTAKE = "intake"
    QUALITY = "quality"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    FITNESS = "fitness"
    PRIVACY = "privacy"
    SAFETY = "safety"
    PROVENANCE = "provenance"


class Origin(str, Enum):
    NATIVE = "native"      # deterministic AIDAP evaluator
    SLAI = "slai"          # SLAI agent subsystem via the governed adapter
    MODEL = "model"        # learned / model-assisted: capped at REVIEW


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"                 # ran, produced findings above INFO
    UNKNOWN = "unknown"               # could not reach a conclusion
    NOT_EVALUATED = "not_evaluated"   # skipped (unsupported input, budget, plan, withheld)
    ERROR = "error"                   # evaluator raised / returned a malformed result

    @property
    def conclusive(self) -> bool:
        return self in (CheckStatus.PASSED, CheckStatus.FAILED)


class UnknownReason(str, Enum):
    UNSUPPORTED_INPUT = "unsupported_input"
    NO_BASELINE = "no_baseline"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    BUDGET = "budget"
    PLAN = "plan"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    EVALUATOR_ERROR = "evaluator_error"
    WITHHELD_PRIVACY = "withheld_privacy"
    TIMEOUT = "timeout"
    MALFORMED_RESULT = "malformed_result"
    NOT_CONFIGURED = "not_configured"
    NOT_APPLICABLE = "not_applicable"


class FailureClass(str, Enum):
    STRUCTURAL = "structural_integrity"
    POPULATION = "population_quality"
    TEMPORAL = "temporal_validity"
    CONTEXTUAL = "contextual_fitness"
    SEMANTIC = "semantic_consistency"
    PRIVACY = "privacy_authorization"
    ADVERSARIAL = "adversarial_input"
    PROVENANCE = "provenance_uncertainty"


@dataclass(frozen=True)
class CheckSpec:
    id: str
    category: Category
    stage: int
    title: str
    method: str                     # "D" deterministic, "S" statistical, "M" model-assisted
    description: str
    failure_class: FailureClass | None = None
    default_mandatory: bool = False
    origin: Origin = Origin.NATIVE
    external: bool = False          # may send content outside the local process (model-assisted)
    needs_baseline: bool = False


@dataclass
class EvidencePointer:
    """Points at the evidence without embedding unredacted sensitive content."""

    path: str = ""                  # JSON pointer / "row 12 / email"
    start: int | None = None
    end: int | None = None
    excerpt: str = ""               # redacted excerpt
    digest: str = ""                # digest of the un-redacted span (identity, not content)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "start": self.start, "end": self.end,
                "excerpt": self.excerpt, "digest": self.digest}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "EvidencePointer":
        d = d or {}
        return cls(d.get("path", ""), d.get("start"), d.get("end"), d.get("excerpt", ""), d.get("digest", ""))


@dataclass
class Finding:
    id: str
    check_id: str
    category: Category
    code: str                       # stable reason code, e.g. "temporal.expired"
    title: str
    severity: Severity
    observed: str                   # what was observed (facts only)
    inference: str                  # what the detector infers from that
    confidence: Confidence
    recommended_action: str
    origin: Origin = Origin.NATIVE
    pointers: list[EvidencePointer] = field(default_factory=list)
    count: int = 1
    mandatory: bool = False
    tags: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)   # small, non-sensitive structured detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "check_id": self.check_id, "category": self.category.value,
            "code": self.code, "title": self.title, "severity": self.severity.value,
            "observed": self.observed, "inference": self.inference,
            "confidence": self.confidence.to_dict(), "recommended_action": self.recommended_action,
            "origin": self.origin.value, "pointers": [p.to_dict() for p in self.pointers],
            "count": self.count, "mandatory": self.mandatory, "tags": list(self.tags),
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        return cls(
            id=d["id"], check_id=d["check_id"], category=Category(d["category"]), code=d["code"],
            title=d.get("title", ""), severity=Severity.parse(d.get("severity")),
            observed=d.get("observed", ""), inference=d.get("inference", ""),
            confidence=Confidence.from_dict(d.get("confidence")),
            recommended_action=d.get("recommended_action", ""),
            origin=Origin(d.get("origin", "native")),
            pointers=[EvidencePointer.from_dict(p) for p in d.get("pointers", [])],
            count=int(d.get("count", 1)), mandatory=bool(d.get("mandatory", False)),
            tags=list(d.get("tags", [])), data=dict(d.get("data", {})),
        )


@dataclass
class CheckResult:
    check_id: str
    status: CheckStatus
    findings: list[Finding] = field(default_factory=list)
    evaluator: str = ""             # evaluator name
    evaluator_version: str = ""
    origin: Origin = Origin.NATIVE
    mandatory: bool = False
    coverage: float | None = None   # 0..1 share of the input actually examined
    unknown_reason: UnknownReason | None = None
    message: str = ""
    duration_ms: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id, "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings], "evaluator": self.evaluator,
            "evaluator_version": self.evaluator_version, "origin": self.origin.value,
            "mandatory": self.mandatory, "coverage": self.coverage,
            "unknown_reason": self.unknown_reason.value if self.unknown_reason else None,
            "message": self.message, "duration_ms": self.duration_ms, "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CheckResult":
        return cls(
            check_id=d["check_id"], status=CheckStatus(d["status"]),
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            evaluator=d.get("evaluator", ""), evaluator_version=d.get("evaluator_version", ""),
            origin=Origin(d.get("origin", "native")), mandatory=bool(d.get("mandatory", False)),
            coverage=d.get("coverage"),
            unknown_reason=UnknownReason(d["unknown_reason"]) if d.get("unknown_reason") else None,
            message=d.get("message", ""), duration_ms=int(d.get("duration_ms", 0)),
            metrics=dict(d.get("metrics", {})),
        )
