"""SLAI Reader as AIDAP's reader for PDF and DOCX (implements ``assurance_engine.ingestion.documents.DocumentReader``).

AIDAP's own parsers cover text, Markdown, HTML, JSON(L) and CSV/TSV. PDF and Word are the formats RAG corpora are mostly made of, and
SLAI already has content-based detection, container/PDF integrity checks and extraction in ``src/agents/reader``; this adapter
runs them in a sandboxed child process (``_reader_worker.py``) and translates the result into AIDAP's contract. Anything the
worker cannot establish is reported as an error with zero coverage - never as an empty, successful read.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ..assurance_engine.normalization.isolation import IsolationUnavailable, child_env, run_worker
from .runtime import SLAI_ROOT, slai_present

__all__ = ["ReaderIntake"]

_WORKER = Path(__file__).with_name("_reader_worker.py")


class ReaderIntake:
    name = "slai.reader"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled and slai_present() and (SLAI_ROOT / "src" / "agents" / "reader").is_dir())
        self.reads = 0

    # ------------------------------------------------------------------------------ DocumentReader port
    def read(self, data: bytes, *, filename: str, max_chars: int, timeout_s: float, memory_mb: int) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        self.reads += 1
        try:
            with tempfile.TemporaryDirectory(prefix="aidap-doc-") as work:      # removed even when the child is killed on timeout
                out = run_worker(_WORKER, [str(SLAI_ROOT), str(max_chars), _safe_name(filename), work], data,
                                 timeout_s=timeout_s, env=child_env(timeout_s, memory_mb))
        except IsolationUnavailable:
            return None
        if out.timed_out:
            return _failure(f"reading the document exceeded {timeout_s:.0f}s and was terminated")
        if out.error:
            return _failure("the document reader failed: " + out.error[:200])
        try:
            res = json.loads(out.stdout.decode("utf-8"))
        except ValueError:
            return _failure("the document reader returned malformed output")
        if not isinstance(res, dict) or not res.get("handled"):
            return None
        return res

    # ------------------------------------------------------------------------------------- health
    def health(self, deep: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {"state": "ready" if self.enabled else "unavailable", "formats": ["pdf", "docx"] if self.enabled else [],
                               "uses": "src/agents/reader (DetectionEngine, IntegrityEngine, ParserEngine) in a sandboxed process"}
        if not self.enabled:
            out["note"] = "SLAI is not present or disabled; PDF and DOCX are reported as unsupported"
            return out
        if deep:
            res = self.read(_SELF_TEST_DOCX, filename="selftest.docx", max_chars=10_000, timeout_s=30.0, memory_mb=1024)
            ok = bool(res and res.get("handled") and "AIDAP self-test" in (res.get("text") or "") and not res.get("errors"))
            out["state"] = "ready" if ok else "error"
            out["self_test"] = "passed" if ok else ((res or {}).get("errors") or ["no result"])[:2]
        return out


def _safe_name(name: str) -> str:
    return "".join(ch for ch in (name or "")[:200] if ch.isprintable() and ch not in '"\\') or "upload"


def _failure(msg: str) -> dict[str, Any]:
    return {"handled": True, "format": "", "text": "", "coverage": 0.0, "errors": [msg], "warnings": [], "truncated": False,
            "metadata": {}, "active_content": {}, "hidden_text": [], "document": {}}


def _selftest_docx() -> bytes:
    import io
    import zipfile
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType='
          '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>AIDAP self-test</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


_SELF_TEST_DOCX = _selftest_docx()
