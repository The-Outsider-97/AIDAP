"""Ordering aid only. A score never overrides a rule (whitepaper 7.3.1)."""

from __future__ import annotations

from ...domain.evaluations import Finding, Severity

__all__ = ["SEVERITY_WEIGHTS", "ordering_score"]

SEVERITY_WEIGHTS = {Severity.INFO: 0.0, Severity.LOW: 0.02, Severity.MEDIUM: 0.08, Severity.HIGH: 0.2,
                    Severity.CRITICAL: 0.5}


def ordering_score(findings: list[Finding]) -> float:
    """1.0 = no findings. For sorting review queues; not a probability, not a gate."""
    penalty = sum(SEVERITY_WEIGHTS[f.severity] * min(max(f.count, 1), 5) ** 0.5 for f in findings)
    return round(max(0.0, 1.0 - penalty), 4)
