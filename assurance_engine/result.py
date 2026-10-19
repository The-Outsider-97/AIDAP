"""Engine output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.evaluations import CheckResult
from ..domain.evidence import EvaluatorVersion
from .decisioning import DecisionOutcome, PlannedCheck

__all__ = ["EngineResult"]


@dataclass
class EngineResult:
    normalized: dict[str, Any]                 # NormalizedInput.to_summary()
    planned: list[PlannedCheck]
    results: dict[str, CheckResult]
    outcome: DecisionOutcome
    evaluators: list[EvaluatorVersion]
    stage_log: list[dict[str, Any]] = field(default_factory=list)
    confidence_summary: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    column_stats: dict[str, Any] | None = None
