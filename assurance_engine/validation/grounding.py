"""Grounding of model-assisted findings: cited spans must exist in the input.

A finding that cites text which is not in the input is a hallucination or an
attack on the evaluator and is discarded (counted, never turned into a pass).
"""

from __future__ import annotations

from ...domain.evaluations import Finding, Origin
from ..normalization.models import NormalizedInput

__all__ = ["ground_findings"]


def _path_exists(n: NormalizedInput, path: str) -> bool:
    if path == "text" or path.startswith("text["):
        return not n.is_records
    if path.startswith("records["):
        try:
            idx = int(path[len("records["):path.index("]")])
        except ValueError:
            return False
        return n.is_records and 0 <= idx < len(n.records or [])
    return False


def ground_findings(findings: list[Finding], n: NormalizedInput) -> tuple[list[Finding], int]:
    """Return (grounded findings, number discarded). Only model-origin findings are filtered."""
    kept: list[Finding] = []
    dropped = 0
    for f in findings:
        if f.origin != Origin.MODEL:
            kept.append(f)
            continue
        if not f.pointers or not all(_path_exists(n, p.path) for p in f.pointers):
            dropped += 1
            continue
        kept.append(f)
    return kept, dropped
