"""Every finding must separate observation, inference, confidence, severity and action."""

from __future__ import annotations

from ...domain.evaluations import CheckResult, Confidence, Finding, Severity

__all__ = ["validate_findings"]


def validate_findings(result: CheckResult) -> list[str]:
    problems: list[str] = []
    for f in result.findings:
        if not f.observed.strip():
            problems.append(f"{f.code}: observed evidence is empty")
        if not f.inference.strip():
            problems.append(f"{f.code}: inference is empty")
        if not f.recommended_action.strip():
            problems.append(f"{f.code}: recommended action is empty")
        if not isinstance(f.severity, Severity) or not isinstance(f.confidence, Confidence):
            problems.append(f"{f.code}: severity/confidence malformed")
    return problems
