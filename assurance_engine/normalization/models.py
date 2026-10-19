"""Normalized representation handed to every evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

__all__ = ["ParseInfo", "NormalizedInput", "TextUnit", "iter_text_units"]


@dataclass
class ParseInfo:
    coverage: float = 1.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    format: str = "text"
    encoding: str = "utf-8"
    records_total: int = 0
    records_kept: int = 0
    isolated: bool = False
    ragged_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"coverage": self.coverage, "errors": list(self.errors), "warnings": list(self.warnings),
                "truncated": self.truncated, "format": self.format, "encoding": self.encoding,
                "records_total": self.records_total, "records_kept": self.records_kept,
                "isolated": self.isolated, "ragged_rows": self.ragged_rows}


@dataclass
class TextUnit:
    path: str            # evidence pointer path, e.g. "records[3].email" or "text[120:180]"
    text: str
    offset: int = 0      # offset into NormalizedInput.text (for text kinds)


@dataclass
class NormalizedInput:
    kind: str                                   # "text" | "records"
    format: str                                 # detected format
    media_type: str
    text: str
    records: list[dict[str, Any]] | None
    columns: list[str]
    metadata: dict[str, Any]                    # metadata embedded in the document
    segments: list[list]
    parse: ParseInfo
    original_digest: str
    normalized_digest: str
    size_bytes: int
    decoded_bytes: int
    filename: str = ""
    html: dict[str, Any] = field(default_factory=dict)
    detection: dict[str, Any] = field(default_factory=dict)

    @property
    def is_records(self) -> bool:
        return self.kind == "records" and self.records is not None

    def to_summary(self) -> dict[str, Any]:
        return {"kind": self.kind, "format": self.format, "media_type": self.media_type,
                "columns": list(self.columns), "records": self.parse.records_kept,
                "size_bytes": self.size_bytes, "decoded_bytes": self.decoded_bytes,
                "original_digest": self.original_digest, "normalized_digest": self.normalized_digest,
                "parse": self.parse.to_dict(), "metadata_keys": sorted(self.metadata)}


def iter_text_units(n: NormalizedInput, max_units: int = 500_000) -> Iterator[TextUnit]:
    """Yield text units with evidence-pointer paths: cells for records, paragraphs for text."""
    count = 0
    if n.is_records:
        for i, rec in enumerate(n.records or []):
            for key, val in rec.items():
                if isinstance(val, str) and val:
                    yield TextUnit(f"records[{i}].{key}", val)
                elif isinstance(val, (dict, list)):
                    import json
                    yield TextUnit(f"records[{i}].{key}", json.dumps(val, ensure_ascii=False))
                count += 1
                if count >= max_units:
                    return
        return
    text = n.text
    if not n.segments:
        if text:
            yield TextUnit("text", text, 0)
        return
    for seg in n.segments:
        path, start, end = seg[0], int(seg[1]), int(seg[2])
        yield TextUnit(path, text[start:end], start)
        count += 1
        if count >= max_units:
            return
