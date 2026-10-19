"""The unit of work AIDAP hands to SLAI: bounded, ordered, and (for any external hop) already redacted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..assurance_engine.evaluators.privacy.redact import redact_text
from ..assurance_engine.normalization.models import iter_text_units

__all__ = ["Envelope", "build_envelope", "MAX_UNITS", "MAX_UNIT_CHARS", "MAX_RECORDS"]

MAX_UNITS = 400
MAX_UNIT_CHARS = 4000
MAX_RECORDS = 5000


@dataclass
class Envelope:
    run_id: str
    check_id: str
    purpose: str
    task: str
    units: list[dict[str, str]] = field(default_factory=list)
    records: list[dict[str, Any]] | None = None
    truncated: bool = False
    redacted: bool = False
    coverage: float = 1.0

    def text(self, sep: str = "\n\n") -> str:
        return sep.join(u["text"] for u in self.units)


def build_envelope(ctx: Any, *, run_id: str, check_id: str, redact: bool = False) -> Envelope:
    """Collect up to ``MAX_UNITS`` text units. ``coverage`` states honestly how much of the input was included."""
    units: list[dict[str, str]] = []
    total = 0
    for unit in iter_text_units(ctx.norm):
        path, text = unit.path, unit.text
        total += 1
        if len(units) >= MAX_UNITS:
            continue
        t = text[:MAX_UNIT_CHARS]
        if redact:
            t = redact_text(t)
        units.append({"path": path, "text": t})
    records = None
    if getattr(ctx.norm, "is_records", False) and ctx.norm.records:
        records = list(ctx.norm.records[:MAX_RECORDS])
    truncated = total > len(units) or (records is not None and len(ctx.norm.records or []) > len(records))
    cov = 1.0 if not total else round(min(1.0, len(units) / total), 4)
    return Envelope(run_id, check_id, ctx.profile.privacy.purpose or ctx.profile.task, ctx.profile.task, units, records,
                    truncated, redact, cov)
