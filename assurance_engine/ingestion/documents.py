"""Port for reading binary document formats (PDF, DOCX) that AIDAP's own text parsers do not handle.

The engine knows only this contract. The SLAI adapter (``slai/reader_intake.py``) implements it with SLAI's Reader
subsystem in a sandboxed child process; without it, those formats stay "unsupported" and are reported as such.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["DocumentReader", "DOCUMENT_FORMATS"]

DOCUMENT_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@runtime_checkable
class DocumentReader(Protocol):
    def read(self, data: bytes, *, filename: str, max_chars: int, timeout_s: float, memory_mb: int) -> dict[str, Any] | None:
        """Return ``None`` when the reader cannot handle this content at all, else a dict:

        ``handled`` (bool) · ``format`` ("pdf" | "docx") · ``text`` · ``coverage`` 0..1 · ``errors`` / ``warnings`` (list[str]) ·
        ``truncated`` · ``metadata`` (document properties: title, author, created, modified) ·
        ``document`` (detection/integrity summary) · ``active_content`` (counts of scripts, macros, embedded files, external links) ·
        ``hidden_text`` (list of strings that are present in the file but not visible to a person reading it).
        A failure to read must be reported as ``errors`` with ``coverage`` 0 - never as an empty successful read."""
