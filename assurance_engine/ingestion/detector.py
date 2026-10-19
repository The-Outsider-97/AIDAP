"""Format sniffing from bytes. Declared types and extensions are hints, not truth."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

__all__ = ["Detection", "detect", "SUPPORTED_FORMATS", "BINARY_SIGNATURES"]

SUPPORTED_FORMATS = ("text", "markdown", "html", "json", "jsonl", "csv", "tsv")

# (signature prefix, kind, human label, risk class)
BINARY_SIGNATURES: tuple[tuple[bytes, str, str, str], ...] = (
    (b"MZ", "executable", "Windows executable (PE)", "executable"),
    (b"\x7fELF", "executable", "ELF executable", "executable"),
    (b"\xcf\xfa\xed\xfe", "executable", "Mach-O executable", "executable"),
    (b"\xce\xfa\xed\xfe", "executable", "Mach-O executable", "executable"),
    (b"\xca\xfe\xba\xbe", "executable", "Java class / Mach-O universal", "executable"),
    (b"#!", "script", "Shell script (shebang)", "script"),
    (b"%PDF", "pdf", "PDF document", "document"),
    (b"PK\x03\x04", "zip", "ZIP container (Office/ZIP)", "archive"),
    (b"\xd0\xcf\x11\xe0", "ole", "Legacy Office (OLE2) container", "macro_container"),
    (b"\x1f\x8b", "gzip", "gzip archive", "archive"),
    (b"Rar!", "rar", "RAR archive", "archive"),
    (b"7z\xbc\xaf\x27\x1c", "7z", "7-Zip archive", "archive"),
    (b"\x89PNG", "image", "PNG image", "image"),
    (b"\xff\xd8\xff", "image", "JPEG image", "image"),
    (b"GIF8", "image", "GIF image", "image"),
    (b"SQLite format 3", "database", "SQLite database", "database"),
)

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

_EXT = {".txt": "text", ".text": "text", ".md": "markdown", ".markdown": "markdown", ".html": "html",
        ".htm": "html", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".csv": "csv", ".tsv": "tsv"}
_MEDIA = {"text/plain": "text", "text/markdown": "markdown", "text/html": "html", "application/json": "json",
          "application/x-ndjson": "jsonl", "application/jsonl": "jsonl", "text/csv": "csv",
          "text/tab-separated-values": "tsv"}


@dataclass
class Detection:
    format: str                      # one of SUPPORTED_FORMATS or "binary"
    media_type: str
    binary_kind: str = ""            # executable | script | pdf | zip | ole | ...
    binary_label: str = ""
    risk_class: str = ""             # executable | archive | macro_container | script | ...
    supported: bool = True
    eicar: bool = False
    mismatch: str = ""               # declared type disagrees with content
    notes: list[str] = field(default_factory=list)


def _ext(filename: str) -> str:
    m = re.search(r"(\.[A-Za-z0-9]{1,8})$", filename or "")
    return m.group(1).lower() if m else ""


def detect(data: bytes, filename: str = "", declared_media_type: str = "") -> Detection:
    head = data[:4096]
    eicar = EICAR in data[:1_000_000]
    for sig, kind, label, risk in BINARY_SIGNATURES:
        if head.startswith(sig):
            if kind == "script":   # '#!' at file start: treat as script, not text
                return Detection("binary", "text/x-script", kind, label, risk, False, eicar)
            return Detection("binary", "application/octet-stream", kind, label, risk, False, eicar)
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return Detection("binary", "application/octet-stream", "unknown_binary", "Unrecognised binary data",
                         "binary", False, eicar)

    declared = _MEDIA.get((declared_media_type or "").split(";")[0].strip().lower(), "")
    ext_fmt = _EXT.get(_ext(filename), "")
    try:
        sample = head.decode("utf-8", errors="ignore").lstrip("﻿ \t\r\n")
    except Exception:  # pragma: no cover - decode with ignore cannot fail
        sample = ""
    low = sample[:300].lower()
    sniff = ""
    if low.startswith(("<!doctype html", "<html")) or re.match(r"<\s*(head|body|div|p)\b", low):
        sniff = "html"
    elif sample.startswith(("{", "[")):
        sniff = "jsonl" if ext_fmt == "jsonl" else "json"
        if sample.startswith("{"):
            lines = [ln for ln in head.decode("utf-8", errors="ignore").splitlines() if ln.strip()][:5]
            if len(lines) >= 2 and all(ln.lstrip().startswith("{") and ln.rstrip().endswith("}") for ln in lines):
                try:
                    for ln in lines:
                        json.loads(ln)
                    sniff = "jsonl"
                except ValueError:
                    pass
    fmt = ext_fmt or declared or sniff or "text"
    mismatch = ""
    if sniff and fmt in ("json", "jsonl", "html") and sniff != fmt and not (sniff == "json" and fmt == "jsonl"):
        mismatch = f"content looks like {sniff} but was declared as {fmt}"
        fmt = sniff
    if fmt == "text" and sniff in ("html", "json"):
        fmt = sniff
    if fmt in ("csv", "tsv") and (sniff in ("html",)):
        mismatch = f"content looks like {sniff} but was declared as {fmt}"
        fmt = sniff
    media = {"text": "text/plain", "markdown": "text/markdown", "html": "text/html",
             "json": "application/json", "jsonl": "application/x-ndjson", "csv": "text/csv",
             "tsv": "text/tab-separated-values"}[fmt]
    return Detection(fmt, media, supported=True, eicar=eicar, mismatch=mismatch)
