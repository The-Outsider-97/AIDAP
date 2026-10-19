"""Dependency-free PDF writer (Helvetica, A4, wrapped text, pagination). Enough for a readable assurance report."""

from __future__ import annotations

from typing import Any

__all__ = ["render_pdf"]

_W, _H, _M = 595, 842, 50
_REGULAR_W = 0.5  # average glyph width factor for wrapping (Helvetica ~0.5 em)


def _enc(s: str) -> bytes:
    return s.encode("cp1252", "replace")


def _esc(b: bytes) -> bytes:
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _wrap(text: str, size: float, width: float) -> list[str]:
    per = max(10, int(width / (size * _REGULAR_W)))
    lines: list[str] = []
    for para in str(text).splitlines() or [""]:
        words, cur = para.split(" "), ""
        for w in words:
            while len(w) > per:                       # break unbreakable tokens (digests, paths)
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:per])
                w = w[per:]
            if len(cur) + len(w) + (1 if cur else 0) <= per:
                cur = f"{cur} {w}" if cur else w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


class _Doc:
    def __init__(self) -> None:
        self.pages: list[list[bytes]] = [[]]
        self.y = _H - _M

    def _emit(self, font: str, size: float, x: float, text: str, color: tuple[float, float, float]) -> None:
        r, g, b = color
        self.pages[-1].append(b"BT /%s %.1f Tf %.2f %.2f %.2f rg %.1f %.1f Td (%s) Tj ET" %
                              (font.encode(), size, r, g, b, x, self.y, _esc(_enc(text))))

    def line(self, text: str, *, size: float = 10, bold: bool = False, gap: float = 3, indent: float = 0,
             color: tuple[float, float, float] = (0.08, 0.1, 0.12)) -> None:
        for ln in _wrap(text, size, _W - 2 * _M - indent):
            if self.y < _M + size:
                self.pages.append([])
                self.y = _H - _M
            self._emit("F2" if bold else "F1", size, _M + indent, ln, color)
            self.y -= size + gap
        # no trailing gap: callers add spacing explicitly

    def space(self, h: float) -> None:
        self.y -= h

    def bytes(self) -> bytes:
        objs: list[bytes] = []

        def add(b: bytes) -> int:
            objs.append(b)
            return len(objs)
        add(b"<< /Type /Catalog /Pages 2 0 R >>")
        add(b"")  # pages placeholder (obj 2)
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")       # 3 = F1
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")  # 4 = F2
        kids = []
        for content in self.pages:
            stream = b"\n".join(content)
            cid = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
            pid = add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                      % (_W, _H, cid))
            kids.append(pid)
        objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        return bytes(out)


_COLORS = {"pass": (0.1, 0.5, 0.29), "review": (0.7, 0.42, 0.0), "quarantine": (0.7, 0.15, 0.12), "block": (0.55, 0.11, 0.09)}


def render_pdf(r: dict[str, Any]) -> bytes:
    d, run = r["decision"], r["run"]
    doc = _Doc()
    doc.line("AIDAP assurance report", size=9, color=(0.4, 0.43, 0.5))
    doc.line(run.get("filename") or run.get("label") or run["id"], size=17, bold=True, gap=5)
    doc.line(f"{d['decision'].upper()}  -  status {d['status']}, disposition {d['disposition']}, release "
             f"{'authorised' if d['release_authorized'] else 'not authorised'}{'  [SHADOW: advisory only]' if d['shadow'] else ''}",
             size=11, bold=True, color=_COLORS.get(d["decision"], (0.2, 0.2, 0.2)))
    doc.space(4)
    doc.line(d["summary"], size=10.5)
    if d["next_action"]:
        doc.line(d["next_action"], size=10, color=(0.35, 0.38, 0.45))
    doc.space(8)
    doc.line("Run", size=12, bold=True)
    for k, v in (("Run", run["id"]), ("Profile", d["profile_ref"]), ("Policy", d["policy_ref"]), ("Submitted by", run.get("created_by")),
                 ("Submitted", run.get("created_at")), ("Input digest", d["input_digest"]), ("Valid until", d.get("expires_at")),
                 ("Decided by", d["decided_by"]), ("Generated", r["generated_at"])):
        doc.line(f"{k}: {v if v not in (None, '') else '-'}", size=9.5, indent=8)
    doc.space(8)
    doc.line("Reasons", size=12, bold=True)
    for x in d["reasons"] or []:
        doc.line(f"[{x['effect']}] {x['code']}" + (f"  (waived by {x['waived_by']})" if x.get("waived_by") else ""), size=9.5, bold=True, indent=8)
        doc.line(x["message"], size=9.5, indent=16)
    if not d["reasons"]:
        doc.line("No blocking or reviewable reasons.", size=9.5, indent=8)
    doc.space(8)
    doc.line("Checks", size=12, bold=True)
    for c in r["checks"]:
        cov = "-" if c["coverage"] is None else f"{round(c['coverage'] * 100)}%"
        doc.line(f"{c['check_id']}{' *' if c['mandatory'] else ''}: {c['status']}, coverage {cov}, {c['findings']} finding(s) [{c['origin']}]",
                 size=9, indent=8)
    doc.line("* mandatory under the policy", size=8.5, indent=8, color=(0.4, 0.43, 0.5))
    doc.space(8)
    doc.line(f"Findings ({len(r['findings'])})", size=12, bold=True)
    for f in r["findings"][:150]:
        conf = (f.get("confidence") or {}).get("basis", "")
        doc.line(f"{f['severity'].upper()}  {f['title']}  ({f['code']}, {conf})", size=9.5, bold=True, indent=8)
        doc.line(f"Observed: {f['observed']}", size=9, indent=16)
        doc.line(f"Inference: {f['inference']}", size=9, indent=16)
        doc.line(f"Recommended: {f['recommended_action']}", size=9, indent=16)
        doc.space(3)
    if r["exceptions"]:
        doc.line("Exceptions", size=12, bold=True)
        for x in r["exceptions"]:
            doc.line(f"{x['id']}: {', '.join(x['reason_codes'])} - by {x['granted_by']} ({x['granted_role']}), expires {x['expires_at']}"
                     f"{' [revoked]' if x['revoked'] else ''}", size=9, indent=8)
            doc.line(f"Justification: {x['justification']}", size=9, indent=16)
    doc.space(8)
    doc.line("Evidence", size=12, bold=True)
    doc.line(f"Seal (SHA-256): {r['evidence']['seal']}", size=9, indent=8)
    doc.space(6)
    doc.line("Notes", size=12, bold=True)
    for n in r["notes"]:
        doc.line("- " + n, size=8.5, indent=8, color=(0.35, 0.38, 0.45))
    return doc.bytes()
