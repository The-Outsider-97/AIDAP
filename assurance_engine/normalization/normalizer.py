"""Normalization: preserve the original digest, decode, create canonical text/records."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from ...domain.utils.domain_helpers import digest_ref
from ..ingestion.detector import Detection, detect
from ..ingestion.loader import Limits
from .canonicalizer import canonical_text, normalized_digest
from .isolation import IsolationUnavailable, parse_isolated
from .models import NormalizedInput, ParseInfo

__all__ = ["normalize"]

_parsers_mod = None


def _parsers():
    global _parsers_mod
    if _parsers_mod is None:
        spec = importlib.util.spec_from_file_location("aidap_parsers_inproc", Path(__file__).with_name("parsers.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _parsers_mod = mod
    return _parsers_mod


def normalize(data: bytes, *, filename: str = "", declared_media_type: str = "", limits: Limits | None = None,
              isolate: bool = True) -> NormalizedInput:
    limits = limits or Limits()
    original = digest_ref(data)
    det: Detection = detect(data, filename, declared_media_type)
    if det.format == "binary":
        info = ParseInfo(coverage=0.0, errors=[f"unsupported format: {det.binary_label or 'binary data'}"],
                         format="binary", encoding="n/a")
        return NormalizedInput("text", "binary", det.media_type, "", None, [], {}, [], info, original,
                               normalized_digest("text", "", None), len(data), 0, filename,
                               detection=_det(det))
    isolated = False
    if isolate:
        try:
            raw = parse_isolated(data, det.format, max_records=limits.max_records, max_chars=limits.max_chars,
                                 timeout_s=limits.parse_timeout_s, memory_mb=limits.parse_memory_mb)
            isolated = True
        except IsolationUnavailable:
            raw = _parsers().parse(data, det.format, max_records=limits.max_records, max_chars=limits.max_chars)
    else:
        raw = _parsers().parse(data, det.format, max_records=limits.max_records, max_chars=limits.max_chars)
    p = raw.get("parse", {})
    info = ParseInfo(float(p.get("coverage", 0.0)), list(p.get("errors", [])), list(p.get("warnings", [])),
                     bool(p.get("truncated", False)), p.get("format", det.format), p.get("encoding", ""),
                     int(p.get("records_total", 0)), int(p.get("records_kept", 0)), isolated,
                     int(p.get("ragged_rows", 0)))
    if det.mismatch:
        info.warnings.append(det.mismatch)
    kind = raw.get("kind", "text")
    text = canonical_text(raw.get("text", "")) if kind == "text" else raw.get("text", "")
    records = raw.get("records")
    meta = {str(k).lower(): v for k, v in (raw.get("metadata") or {}).items()}
    return NormalizedInput(kind, det.format, det.media_type, text, records, list(raw.get("columns", [])), meta,
                           raw.get("segments", []), info, original, normalized_digest(kind, text, records),
                           len(data), len(text.encode("utf-8")) if kind == "text" else len(data), filename,
                           raw.get("html", {}), _det(det))


def _det(d: Detection) -> dict[str, Any]:
    return {"format": d.format, "media_type": d.media_type, "binary_kind": d.binary_kind,
            "binary_label": d.binary_label, "risk_class": d.risk_class, "eicar": d.eicar,
            "mismatch": d.mismatch}
