"""Strict validation of reasoning payloads returned across the SLAI port."""

from __future__ import annotations

from typing import Any

from ...domain.evaluations import Severity
from ...domain.utils.domain_errors import ValidationFailed

__all__ = ["validate_reasoning_payload"]

_SEVERITIES = {s.value for s in Severity}


def validate_reasoning_payload(payload: Any) -> list[dict[str, Any]]:
    """Return clean finding dicts or raise ``ValidationFailed``.

    An arbitrary model response must never become authoritative state, so anything
    that is not an exact, bounded structure is rejected rather than repaired.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        raise ValidationFailed("reasoning payload must be an object with a 'findings' list")
    if len(payload["findings"]) > 50:
        raise ValidationFailed("too many findings in reasoning payload")
    clean: list[dict[str, Any]] = []
    for i, f in enumerate(payload["findings"]):
        if not isinstance(f, dict):
            raise ValidationFailed(f"finding {i} is not an object")
        code = f.get("code")
        if not isinstance(code, str) or not code.startswith("slai.") or len(code) > 80:
            raise ValidationFailed(f"finding {i}: code must be a string starting with 'slai.'")
        sev = str(f.get("severity", "")).lower()
        if sev not in _SEVERITIES:
            raise ValidationFailed(f"finding {i}: unknown severity")
        for key in ("title", "observed", "inference", "recommended_action"):
            v = f.get(key)
            if not isinstance(v, str) or not v.strip() or len(v) > 2000:
                raise ValidationFailed(f"finding {i}: '{key}' must be a non-empty string up to 2000 characters")
        spans = f.get("spans", [])
        if not isinstance(spans, list) or len(spans) > 10:
            raise ValidationFailed(f"finding {i}: spans must be a list of at most 10")
        for s in spans:
            if not (isinstance(s, dict) and isinstance(s.get("path"), str) and isinstance(s.get("start"), int)
                    and isinstance(s.get("end"), int) and 0 <= s["start"] <= s["end"]):
                raise ValidationFailed(f"finding {i}: malformed span")
        clean.append({**f, "severity": sev})
    return clean
