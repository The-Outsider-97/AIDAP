"""Confidence semantics.

The whitepaper forbids invented certainty: a value is either deterministic
(a rule matched exactly), heuristic (a detector with unmeasured error), or
unknown. AIDAP never labels a value *calibrated* until labelled evidence
exists, so ``CALIBRATED`` is intentionally not representable here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["ConfidenceBasis", "ConfidenceInterpretation", "Confidence"]


class ConfidenceBasis(str, Enum):
    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


class ConfidenceInterpretation(str, Enum):
    EXACT_RULE = "exact_rule"                 # rule matched exactly as written
    VALIDATED_PATTERN = "validated_pattern"   # pattern + checksum/structure validated
    UNCALIBRATED_SCORE = "uncalibrated_score"  # a score exists but is not a probability
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class Confidence:
    basis: ConfidenceBasis
    interpretation: ConfidenceInterpretation
    value: float | None = None       # only a relative score; never a calibrated probability
    note: str = ""

    @classmethod
    def deterministic(cls, note: str = "") -> "Confidence":
        return cls(ConfidenceBasis.DETERMINISTIC, ConfidenceInterpretation.EXACT_RULE, 1.0, note)

    @classmethod
    def validated(cls, note: str = "") -> "Confidence":
        return cls(ConfidenceBasis.DETERMINISTIC, ConfidenceInterpretation.VALIDATED_PATTERN, 1.0, note)

    @classmethod
    def heuristic(cls, score: float | None = None, note: str = "") -> "Confidence":
        return cls(ConfidenceBasis.HEURISTIC, ConfidenceInterpretation.UNCALIBRATED_SCORE,
                   None if score is None else round(float(score), 4), note)

    @classmethod
    def unknown(cls, note: str = "") -> "Confidence":
        return cls(ConfidenceBasis.UNKNOWN, ConfidenceInterpretation.NOT_ASSESSED, None, note)

    def to_dict(self) -> dict:
        return {"basis": self.basis.value, "interpretation": self.interpretation.value,
                "value": self.value, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Confidence":
        if not data:
            return cls.unknown()
        return cls(ConfidenceBasis(data.get("basis", "unknown")),
                   ConfidenceInterpretation(data.get("interpretation", "not_assessed")),
                   data.get("value"), data.get("note", ""))
