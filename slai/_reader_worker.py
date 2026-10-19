"""Child-process entry point: read one PDF/DOCX with SLAI's Reader subsystem and print one JSON document.

    python -I _reader_worker.py <slai_root> <max_chars> <filename> <workdir>      (file bytes on stdin)

``workdir`` is a fresh directory the parent creates and removes after this process ends (also when it is killed on timeout).

Why a separate process: PDF and Word files are hostile-input formats. The parent never opens them. This process has CPU,
memory, file-size and process-count limits (POSIX) and a wall-clock timeout set by the parent.

What it uses from SLAI (``src/agents/reader``): ``DetectionEngine`` (content-based format identity, encrypted/damaged
containers), ``IntegrityEngine`` (container and PDF structure checks incl. the shared ``ExpansionGuard``) and ``ParserEngine``
(text extraction). ``ReaderMemory`` is deliberately not used: it persists parsed content to disk, which would put customer
content outside AIDAP's retention and deletion controls. SLAI's logger is replaced by a silent one for the same reason.
What it adds itself: active-content, hidden-text and document-property inspection, which Reader does not provide.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import types
import zipfile

MAX_PARTS = 400          # cap on samples/lists that leave this process


def _limit(data_len: int) -> None:
    try:
        import resource
        cpu = int(os.environ.get("AIDAP_PARSE_CPU_S", "20"))
        mem = int(os.environ.get("AIDAP_PARSE_MEM_MB", "1024")) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        fs = max(16 << 20, 2 * data_len)
        resource.setrlimit(resource.RLIMIT_FSIZE, (fs, fs))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        except (ValueError, OSError):
            pass
    except ImportError:
        pass


def _silence_slai_logging() -> None:
    import logging
    mod, lg = types.ModuleType("logs"), types.ModuleType("logs.logger")

    def get_logger(name: str = "reader", *a, **k):
        log = logging.getLogger(name)
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return log

    class PrettyPrinter:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    lg.get_logger, lg.PrettyPrinter = get_logger, PrettyPrinter
    lg.__getattr__ = lambda _n: (lambda *a, **k: None)          # any other helper SLAI's logger offers is a no-op here
    mod.logger = lg
    sys.modules["logs"], sys.modules["logs.logger"] = mod, lg


def _out(obj: dict) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    return 0


_WORKDIR = ""


def _clean(msg: str) -> str:
    """Error text may quote the temporary path; the uploaded file's location in this sandbox means nothing outside it."""
    return msg.replace(_WORKDIR, "<file>") if _WORKDIR else msg


def _fail(msg: str, **extra) -> int:
    return _out({"handled": True, "text": "", "coverage": 0.0, "errors": [_clean(msg)], "warnings": [], "truncated": False,
                 "metadata": {}, "active_content": {}, "hidden_text": [], **extra})


# ----------------------------------------------------------------------------------------------- DOCX inspection
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_REL_EXT = re.compile(rb'<Relationship\b[^>]*?>', re.I)
_ATTR = re.compile(rb'(\w+)="([^"]*)"')


def _no_dtd(xml: bytes) -> bool:
    head = xml[:65536].lower()
    return b"<!doctype" not in head and b"<!entity" not in head


def _docx_inspect(raw: bytes, guard, max_chars: int) -> dict:
    from xml.etree import ElementTree as ET
    res = {"active": {"macros": False, "embedded_objects": 0, "activex": 0, "external_links": 0, "remote_template": False},
           "hidden": [], "meta": {}, "error": ""}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        low = [n.lower() for n in names]
        res["active"]["macros"] = any(n.endswith("vbaproject.bin") for n in low)
        res["active"]["embedded_objects"] = sum(1 for n in low if n.startswith("word/embeddings/"))
        res["active"]["activex"] = sum(1 for n in low if "/activex/" in n)
        try:
            ct = guard.read_member(z, "[Content_Types].xml", source="docx", limit=1 << 20)
            if b"macroenabled" in ct.lower():
                res["active"]["macros"] = True
        except Exception:                                   # noqa: BLE001 - integrity engine already judged the package
            pass
        for n in [n for n in names if n.lower().endswith(".rels")][:200]:
            try:
                rels = guard.read_member(z, n, source="docx", limit=1 << 20)
            except Exception:                               # noqa: BLE001
                continue
            for m in _REL_EXT.finditer(rels):
                attrs = {k.lower(): v for k, v in _ATTR.findall(m.group(0))}
                if attrs.get(b"targetmode", b"").lower() == b"external":
                    res["active"]["external_links"] += 1
                    if attrs.get(b"type", b"").lower().endswith(b"/attachedtemplate"):
                        res["active"]["remote_template"] = True
        # visible text is what Reader extracts; text marked as hidden is reported so the safety checks can weigh it
        if "word/document.xml" in names:
            xml = guard.read_member(z, "word/document.xml", source="docx", limit=32 << 20)
            if not _no_dtd(xml):
                res["error"] = "word/document.xml declares a DTD or entities, which Word documents never need"
                return res
            root = ET.fromstring(xml)
            for run in root.iter(_W + "r"):
                props = run.find(_W + "rPr")
                if props is None:
                    continue
                v = props.find(_W + "vanish")
                if v is None or str(v.get(_W + "val", "true")).lower() in ("0", "false", "off"):
                    continue
                t = "".join((n.text or "") for n in run.iter(_W + "t")).strip()
                if t:
                    res["hidden"].append(t[:300])
                    if len(res["hidden"]) >= MAX_PARTS:
                        break
        if "docProps/core.xml" in names:
            core = guard.read_member(z, "docProps/core.xml", source="docx", limit=1 << 20)
            if _no_dtd(core):
                try:
                    c = ET.fromstring(core)
                    for tag, key in (("title", "title"), ("creator", "author"), ("created", "created"), ("modified", "modified")):
                        for el in c.iter():
                            if el.tag.rsplit("}", 1)[-1] == tag and (el.text or "").strip():
                                res["meta"][key] = el.text.strip()[:300]
                                break
                except ET.ParseError:
                    pass
    return res


# ------------------------------------------------------------------------------------------------ PDF inspection
def _pdf_inspect(raw: bytes) -> dict:
    import pypdf
    from pypdf.generic import ArrayObject, DictionaryObject
    res = {"active": {"javascript": 0, "launch": 0, "embedded_files": 0, "open_action": False, "xfa": False,
                      "external_uris": 0, "scan": "structure+bytes"}, "meta": {}, "error": ""}
    a = res["active"]

    def action(obj) -> None:
        try:
            obj = obj.get_object()
            if isinstance(obj, DictionaryObject):
                s = str(obj.get("/S", ""))
                if s == "/JavaScript":
                    a["javascript"] += 1
                elif s == "/Launch":
                    a["launch"] += 1
                elif s == "/URI":
                    a["external_uris"] += 1
                nxt = obj.get("/Next")
                if nxt is not None:
                    for item in (nxt.get_object() if isinstance(nxt.get_object(), ArrayObject) else [nxt]):
                        action(item)
        except Exception:                                    # noqa: BLE001 - a malformed action is itself worth the byte scan below
            pass

    try:
        r = pypdf.PdfReader(io.BytesIO(raw), strict=False)
        if not r.is_encrypted:
            root = r.trailer["/Root"]
            if "/OpenAction" in root:
                a["open_action"] = True
                action(root["/OpenAction"])
            if "/AA" in root:
                a["javascript"] += 1
            names = root.get("/Names")
            names = names.get_object() if names is not None else None
            if isinstance(names, DictionaryObject):
                if "/JavaScript" in names:
                    a["javascript"] += 1
                ef = names.get("/EmbeddedFiles")
                if ef is not None:
                    arr = ef.get_object().get("/Names")
                    a["embedded_files"] += max(1, len(arr.get_object()) // 2) if arr is not None else 1
            acro = root.get("/AcroForm")
            if acro is not None and "/XFA" in acro.get_object():
                a["xfa"] = True
            for page in list(r.pages)[:2000]:
                if "/AA" in page:
                    a["javascript"] += 1
                annots = page.get("/Annots")
                for an in (annots.get_object() if annots is not None else [])[:2000]:
                    ao = an.get_object()
                    if "/A" in ao:
                        action(ao["/A"])
                    if str(ao.get("/Subtype", "")) == "/FileAttachment":
                        a["embedded_files"] += 1
            info = r.metadata
            if info is not None:
                for key, attr in (("title", "title"), ("author", "author")):
                    v = getattr(info, attr, None)
                    if v:
                        res["meta"][key] = str(v)[:300]
                for key, attr in (("created", "creation_date"), ("modified", "modification_date")):
                    try:
                        v = getattr(info, attr, None)
                        if v:
                            res["meta"][key] = v.date().isoformat()
                    except Exception:                        # noqa: BLE001
                        pass
    except Exception as exc:                                 # noqa: BLE001
        a["scan"] = "bytes-only"
        res["error"] = f"{exc.__class__.__name__}"
    # byte-level fallback: catches actions in places the structure walk did not reach
    for token, key in ((b"/JavaScript", "javascript"), (b"/JS", "javascript"), (b"/Launch", "launch"),
                       (b"/EmbeddedFile", "embedded_files")):
        if token in raw and not a[key]:
            a[key] = 1
    return res


# ------------------------------------------------------------------------------------------------------- main
def main() -> int:
    slai_root, max_chars, filename = sys.argv[1], int(sys.argv[2]), (sys.argv[3] if len(sys.argv) > 3 else "")[:255]
    data = sys.stdin.buffer.read()
    _limit(len(data))
    _silence_slai_logging()
    if slai_root not in sys.path:
        sys.path.insert(0, slai_root)
    global _WORKDIR
    work = _WORKDIR = os.path.abspath(sys.argv[4])
    os.chdir(work)
    try:
        from src.agents.reader.detection_engine import DetectionEngine
        from src.agents.reader.integrity_engine import ExpansionGuard, IntegrityEngine
        from src.agents.reader.parser_engine import ParserEngine
    except Exception as exc:                                 # noqa: BLE001
        return _out({"handled": False, "reason": f"SLAI Reader is unavailable: {exc.__class__.__name__}: {str(exc)[:160]}"})

    detector = DetectionEngine()
    det = detector.detect(data, name=filename or "upload")["payload"]
    fmt = det.get("format_id")
    if fmt not in ("pdf", "docx"):
        return _out({"handled": False, "reason": f"Reader identified this content as {fmt or 'unknown'}"})
    document = {"format_id": fmt, "detected_by": det.get("detected_by"), "confidence": det.get("confidence"),
                "extension": det.get("extension"), "extension_mismatch": bool(det.get("extension_mismatch")),
                "encrypted": det.get("encrypted"), "damaged": bool(det.get("damaged")),
                "reader": "SLAI Reader (DetectionEngine, IntegrityEngine, ParserEngine)"}
    mime = det.get("mime") or ""
    path = os.path.join(work, "input." + fmt)                # content-derived name: the uploaded name never touches the filesystem
    with open(path, "wb") as fh:
        fh.write(data)

    report = IntegrityEngine(detector).validate_file(path, expected_format=fmt, deep=True, compute_hash=False)
    payload = report.get("payload", {})
    failed = [c for c in payload.get("checks", []) if not c.get("ok") and c.get("severity") == "error" and not c.get("skipped")]
    document["integrity"] = payload.get("integrity_status", report.get("status"))
    document["integrity_failures"] = [_clean(f"{c['name']}: {c.get('detail')}") if c.get("detail") else c["name"] for c in failed][:10]
    document["checks_run"] = sum(1 for c in payload.get("checks", []) if not c.get("skipped"))
    document["checks_skipped"] = [c["name"] for c in payload.get("checks", []) if c.get("skipped")][:10]
    base = {"format": fmt, "media_type": mime, "document": document}
    if det.get("encrypted"):
        return _fail("the document is encrypted, so its content cannot be read", **base)
    if failed:
        return _fail("the file failed Reader's integrity checks: " + "; ".join(document["integrity_failures"][:3]), **base)

    guard = ExpansionGuard()
    try:
        inspected = _docx_inspect(data, guard, max_chars) if fmt == "docx" else _pdf_inspect(data)
    except Exception as exc:                                 # noqa: BLE001
        return _fail(f"the document could not be inspected safely ({exc.__class__.__name__})", **base)
    if inspected.get("error") and fmt == "docx":
        return _fail(inspected["error"], **base)

    parser = ParserEngine(memory=None)
    parser.pdf_extract_page_breaks = False                   # page markers would become part of the checked text
    try:
        parsed = parser.parse(path)
    except Exception as exc:                                 # noqa: BLE001
        return _fail(f"{exc.__class__.__name__}: {str(exc)[:200]}", active_content=inspected["active"], **base)
    text = parsed.get("content", "") or ""
    pm = (parsed.get("metadata") or {}).get("parser_metadata") or {}
    warnings = [str(w) for w in parsed.get("warnings", [])]
    coverage, truncated = 1.0, False
    if fmt == "pdf":
        pages, empty = int(pm.get("page_count") or 0), int(pm.get("empty_pages") or 0)
        got = int(pm.get("pages_extracted") or 0)
        if pages:
            coverage = max(0.0, (min(got, pages) - empty) / pages)
        document.update({"pages": pages, "pages_without_text": empty})
        if empty:
            warnings.append(f"{empty} of {pages} page(s) have no text layer (scanned or image-only); OCR is not performed, so they were not read")
        if got < pages:
            warnings.append(f"only the first {got} of {pages} pages were read")
            truncated = True
    else:
        document["paragraphs"] = pm.get("paragraph_count")
        warnings.append("headers, footers, footnotes, comments and embedded images are not read")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
        coverage = min(coverage, round(max_chars / max(1, len(parsed.get("content", ""))), 4))
        warnings.append("text truncated at the configured limit")
    warnings = [w for w in warnings if w not in ("pdf_empty_pages_detected", "pdf_page_limit_reached")]
    return _out({"handled": True, "text": text, "coverage": round(coverage, 4), "errors": [], "warnings": warnings[:20],
                 "truncated": truncated, "metadata": inspected.get("meta", {}), "active_content": inspected["active"],
                 "hidden_text": inspected.get("hidden", [])[:MAX_PARTS], **base})


if __name__ == "__main__":
    sys.exit(main())
