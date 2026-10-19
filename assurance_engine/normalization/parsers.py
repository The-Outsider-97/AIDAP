"""Hostile-input parsers. Standard library only, no AIDAP imports.

This file is executed both in-process (small, already-vetted inputs) and inside
an isolated child process (``isolation.py``) with CPU/memory limits and a
wall-clock timeout. Parsers never evaluate content: no ``eval``, no YAML object
construction, no entity expansion, no network access.

Every parser returns a plain dict::

    {"kind": "text" | "records",
     "text": str,                 # canonical text (records: concatenated string values per row)
     "records": list[dict] | None,
     "columns": list[str],
     "metadata": dict,            # metadata embedded in the document (front matter, <meta>, ...)
     "segments": [[path, start, end]],   # offsets of text units for evidence pointers
     "parse": {"coverage": float, "errors": [...], "warnings": [...], "truncated": bool,
               "format": str, "encoding": str, "records_total": int, "records_kept": int},
     "html": {...} optional signals for safety checks}
"""

from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser

MAX_RECORDS_DEFAULT = 200_000
MAX_TEXT_CHARS_DEFAULT = 20_000_000
MAX_JSON_DEPTH = 64
MAX_FIELD_CHARS = 1_000_000


def decode_bytes(data: bytes) -> tuple[str, str, list[str]]:
    """Decode to text, reporting the encoding and any replacement."""
    warnings: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig", warnings
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8"), "utf-8", warnings
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        warnings.append("input is not valid UTF-8; invalid bytes were replaced")
        return text, "utf-8-replace", warnings


def _info(fmt: str, encoding: str) -> dict:
    return {"coverage": 1.0, "errors": [], "warnings": [], "truncated": False, "format": fmt,
            "encoding": encoding, "records_total": 0, "records_kept": 0}


def _result(kind: str, text: str, records, columns, metadata, segments, parse, extra=None) -> dict:
    out = {"kind": kind, "text": text, "records": records, "columns": columns, "metadata": metadata,
           "segments": segments, "parse": parse}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------------------------- text
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_KV = re.compile(r"^([A-Za-z_][\w .-]{0,48}?)\s*:\s*(.*)$")


def _front_matter(text: str) -> tuple[dict, str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines()[:100]:
        km = _KV.match(line.strip())
        if km:
            value = km.group(2).strip().strip("'\"")
            meta[km.group(1).strip().lower().replace(" ", "_")] = value[:2000]
    return meta, text[m.end():]


def _paragraph_segments(text: str, max_segments: int = 20000) -> list[list]:
    segments = []
    pos = 0
    for i, para in enumerate(re.split(r"\n\s*\n", text)):
        start = text.find(para, pos) if para else pos
        if start < 0:
            start = pos
        end = start + len(para)
        if para.strip():
            segments.append([f"text[{start}:{end}]", start, end])
        pos = end
        if len(segments) >= max_segments:
            break
    return segments


def parse_text(data: bytes, fmt: str = "text", max_chars: int = MAX_TEXT_CHARS_DEFAULT) -> dict:
    text, enc, warnings = decode_bytes(data)
    info = _info(fmt, enc)
    info["warnings"] += warnings
    if len(text) > max_chars:
        text = text[:max_chars]
        info["truncated"] = True
        info["coverage"] = round(max_chars / max(len(data), 1), 4)
        info["warnings"].append("text truncated at the configured limit")
    meta: dict = {}
    if fmt in ("markdown", "text"):
        meta, text = _front_matter(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _result("text", text, None, [], meta, _paragraph_segments(text), info)


# ---------------------------------------------------------------------------------------------- html
class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.meta: dict = {}
        self.title = ""
        self._skip = 0
        self._in_title = False
        self.scripts = 0
        self.event_handlers = 0
        self.js_urls = 0
        self.hidden_chunks: list[str] = []
        self._hidden_depth: list[bool] = []
        self.iframes = 0
        self.forms = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        self.depth += 1
        if self.depth > 400:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            self.scripts += 1
        if tag in ("iframe", "object", "embed"):
            self.iframes += 1
        if tag == "form":
            self.forms += 1
        if any(k.startswith("on") for k in a):
            self.event_handlers += 1
        for k in ("href", "src", "action"):
            if a.get(k, "").strip().lower().startswith(("javascript:", "data:text/html")):
                self.js_urls += 1
        if tag == "meta":
            name = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if name and "content" in a:
                self.meta[name.replace(" ", "_")] = a["content"][:2000]
        if tag == "title":
            self._in_title = True
        style = a.get("style", "").replace(" ", "").lower()
        hidden = ("hidden" in a or "display:none" in style or "visibility:hidden" in style
                  or "font-size:0" in style or "opacity:0" in style or a.get("aria-hidden") == "true")
        self._hidden_depth.append(hidden)
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        self.depth = max(0, self.depth - 1)
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if self._hidden_depth:
            self._hidden_depth.pop()
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if any(self._hidden_depth):
            if data.strip():
                self.hidden_chunks.append(data.strip()[:400])
            return
        self.parts.append(data)


def parse_html(data: bytes, max_chars: int = MAX_TEXT_CHARS_DEFAULT) -> dict:
    text, enc, warnings = decode_bytes(data)
    info = _info("html", enc)
    info["warnings"] += warnings
    if len(text) > max_chars:
        text = text[:max_chars]
        info["truncated"] = True
        info["warnings"].append("html truncated at the configured limit")
    p = _HTMLText()
    try:
        p.feed(text)
        p.close()
    except Exception as exc:  # malformed markup should degrade, not crash
        info["errors"].append(f"html parse error: {exc.__class__.__name__}")
        info["coverage"] = 0.5
    body = re.sub(r"[ \t\f\v]+", " ", "".join(p.parts))
    body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
    meta = dict(p.meta)
    if p.title.strip():
        meta.setdefault("title", p.title.strip()[:500])
    html_signals = {"scripts": p.scripts, "event_handlers": p.event_handlers, "js_urls": p.js_urls,
                    "iframes": p.iframes, "forms": p.forms, "hidden_text": p.hidden_chunks[:20]}
    return _result("text", body, None, [], meta, _paragraph_segments(body), info, {"html": html_signals})


# ---------------------------------------------------------------------------------------------- json
def _depth_ok(value, depth=0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return False
    if isinstance(value, dict):
        return all(_depth_ok(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return all(_depth_ok(v, depth + 1) for v in value)
    return True


def _flatten(value, prefix="", out=None, depth=0):
    out = {} if out is None else out
    if isinstance(value, dict) and depth < 6:
        for k, v in value.items():
            _flatten(v, f"{prefix}{k}." if prefix or True else k, out, depth + 1)
            if not isinstance(v, (dict, list)):
                out[f"{prefix}{k}"] = v
    elif isinstance(value, list) and depth < 6:
        out[prefix.rstrip(".")] = json.dumps(value, ensure_ascii=False)[:MAX_FIELD_CHARS]
    return out


def _flat_record(rec) -> dict:
    if not isinstance(rec, dict):
        return {"value": rec}
    flat: dict = {}
    for k, v in rec.items():
        if isinstance(v, (dict, list)):
            flat[str(k)] = v
        else:
            flat[str(k)] = v
    return flat


def _records_text(records: list[dict]) -> tuple[str, list[list]]:
    """Concatenate string cells in a stable order; produce per-cell segments."""
    pieces: list[str] = []
    segs: list[list] = []
    pos = 0
    for i, rec in enumerate(records):
        for key, val in rec.items():
            if isinstance(val, str) and val:
                chunk = val if len(val) <= MAX_FIELD_CHARS else val[:MAX_FIELD_CHARS]
                segs.append([f"records[{i}].{key}", pos, pos + len(chunk)])
                pieces.append(chunk)
                pos += len(chunk) + 1
            elif isinstance(val, (dict, list)):
                js = json.dumps(val, ensure_ascii=False)[:MAX_FIELD_CHARS]
                segs.append([f"records[{i}].{key}", pos, pos + len(js)])
                pieces.append(js)
                pos += len(js) + 1
    return "\n".join(pieces), segs


def parse_json(data: bytes, max_records: int = MAX_RECORDS_DEFAULT) -> dict:
    text, enc, warnings = decode_bytes(data)
    info = _info("json", enc)
    info["warnings"] += warnings
    try:
        doc = json.loads(text, parse_constant=lambda c: None)
    except (ValueError, RecursionError) as exc:
        info["errors"].append(f"invalid JSON: {str(exc)[:160]}")
        info["coverage"] = 0.0
        return _result("text", "", None, [], {}, [], info)
    if not _depth_ok(doc):
        info["errors"].append("JSON nesting exceeds the supported depth")
        info["coverage"] = 0.0
        return _result("text", "", None, [], {}, [], info)
    meta: dict = {}
    if isinstance(doc, dict):
        for key in ("metadata", "meta", "_meta"):
            if isinstance(doc.get(key), dict):
                meta = {str(k).lower(): v for k, v in doc[key].items() if not isinstance(v, (dict, list))}
        arr_key = next((k for k, v in doc.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)), None)
        if arr_key:
            for k, v in doc.items():
                if k != arr_key and not isinstance(v, (dict, list)) and k.lower() not in meta:
                    meta[str(k).lower()] = v
            records = doc[arr_key]
        else:
            records = [doc]
    elif isinstance(doc, list):
        records = doc if all(isinstance(x, dict) for x in doc) else [{"value": x} for x in doc]
    else:
        records = [{"value": doc}]
    info["records_total"] = len(records)
    if len(records) > max_records:
        records = records[:max_records]
        info["truncated"] = True
        info["coverage"] = round(max_records / info["records_total"], 4)
        info["warnings"].append(f"only the first {max_records} records were examined")
    info["records_kept"] = len(records)
    records = [_flat_record(r) for r in records]
    cols: list[str] = []
    seen = set()
    for r in records[:2000]:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    t, segs = _records_text(records)
    return _result("records", t, records, cols, meta, segs, info)


def parse_jsonl(data: bytes, max_records: int = MAX_RECORDS_DEFAULT) -> dict:
    text, enc, warnings = decode_bytes(data)
    info = _info("jsonl", enc)
    info["warnings"] += warnings
    records: list[dict] = []
    bad = 0
    total = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        total += 1
        if len(records) >= max_records:
            info["truncated"] = True
            continue
        try:
            obj = json.loads(line)
            if not _depth_ok(obj):
                raise ValueError("depth")
            records.append(_flat_record(obj))
        except (ValueError, RecursionError):
            bad += 1
    info["records_total"] = total
    info["records_kept"] = len(records)
    if total:
        info["coverage"] = round((len(records)) / total, 4)
    if bad:
        info["errors"].append(f"{bad} of {total} lines are not valid JSON")
    cols: list[str] = []
    seen = set()
    for r in records[:2000]:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    t, segs = _records_text(records)
    return _result("records", t, records, cols, {}, segs, info)


# ---------------------------------------------------------------------------------------------- csv
def parse_csv(data: bytes, delimiter: str = ",", max_records: int = MAX_RECORDS_DEFAULT) -> dict:
    text, enc, warnings = decode_bytes(data)
    fmt = "tsv" if delimiter == "\t" else "csv"
    info = _info(fmt, enc)
    info["warnings"] += warnings
    csv.field_size_limit(MAX_FIELD_CHARS)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows: list[list[str]] = []
    try:
        for i, row in enumerate(reader):
            if i > max_records:
                info["truncated"] = True
                break
            rows.append(row)
    except csv.Error as exc:
        info["errors"].append(f"csv error: {str(exc)[:120]}")
    if not rows:
        info["coverage"] = 0.0
        info["errors"].append("no rows")
        return _result("records", "", [], [], {}, [], info)
    header = [h.strip() for h in rows[0]]
    cols = []
    for h in header:
        name = h or f"column_{len(cols) + 1}"
        while name in cols:
            name += "_"
        cols.append(name)
    records: list[dict] = []
    ragged = 0
    for row in rows[1:]:
        if len(row) != len(cols):
            ragged += 1
        rec = {cols[j]: (row[j] if j < len(row) else None) for j in range(len(cols))}
        if len(row) > len(cols):
            rec["_extra"] = delimiter.join(row[len(cols):])
        records.append(rec)
    info["records_total"] = len(rows) - 1
    info["records_kept"] = len(records)
    if ragged:
        info["warnings"].append(f"{ragged} rows have a different number of fields than the header")
        info["ragged_rows"] = ragged
    if info["truncated"]:
        info["coverage"] = round(max_records / max(info["records_total"], max_records + 1), 4)
    t, segs = _records_text(records)
    return _result("records", t, records, cols, {}, segs, info)


def parse(data: bytes, fmt: str, *, max_records: int = MAX_RECORDS_DEFAULT,
          max_chars: int = MAX_TEXT_CHARS_DEFAULT) -> dict:
    if fmt == "json":
        return parse_json(data, max_records)
    if fmt == "jsonl":
        return parse_jsonl(data, max_records)
    if fmt == "csv":
        return parse_csv(data, ",", max_records)
    if fmt == "tsv":
        return parse_csv(data, "\t", max_records)
    if fmt == "html":
        return parse_html(data, max_chars)
    if fmt in ("markdown", "text"):
        return parse_text(data, fmt, max_chars)
    info = _info(fmt, "unknown")
    info["coverage"] = 0.0
    info["errors"].append(f"unsupported format '{fmt}'")
    return _result("text", "", None, [], {}, [], info)
