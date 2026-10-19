"""Redaction of detected spans; also used to sanitise evidence excerpts."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ....domain.data.sensitivity import SensitiveType
from .detectors import Hit, scan_text

__all__ = ["redact_text", "safe_excerpt", "redact_bytes", "mask_for"]


def mask_for(t: SensitiveType) -> str:
    return f"[REDACTED:{t.value}]"


def redact_text(text: str, hits: list[Hit] | None = None, types: set[str] | None = None) -> str:
    hits = scan_text(text) if hits is None else hits
    out: list[str] = []
    pos = 0
    for h in sorted(hits, key=lambda x: x.start):
        if types is not None and h.type.value not in types:
            continue
        if h.start < pos:
            continue
        out.append(text[pos:h.start])
        out.append(mask_for(h.type))
        pos = h.end
    out.append(text[pos:])
    return "".join(out)


def safe_excerpt(text: str, start: int, end: int, *, radius: int = 24, mask_span: bool = True,
                 hide_span: bool = False) -> str:
    """Short context around a span, with every sensitive value (including the span) masked."""
    a, b = max(0, start - radius), min(len(text), end + radius)
    before, span, after = text[a:start], text[start:end], text[end:b]
    if hide_span:
        span = "…"
    elif mask_span and len(span) > 40:
        span = span[:40] + "…"
    snippet = redact_text(before + "\x00" + span + "\x00" + after)
    return snippet.replace("\x00", "").replace("\n", " ")[: 2 * radius + 60]


def redact_bytes(data: bytes, types: set[str] | None = None) -> tuple[bytes, dict[str, Any]]:
    """Redact the whole decoded text of an input, preserving its format and structure.

    Returns the derivative bytes (UTF-8) and a summary. The derivative has a *new* digest
    and must be re-validated as a new input; it inherits no approval.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    hits = [h for h in scan_text(text) if types is None or h.type.value in types]
    counts = Counter(h.type.value for h in hits)
    return redact_text(text, hits).encode("utf-8"), {"redacted": dict(counts), "total": sum(counts.values())}
