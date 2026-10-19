"""Self-contained HTML report. All values are escaped; no scripts, no external resources."""

from __future__ import annotations

from html import escape as e
from typing import Any

__all__ = ["render_html"]

_COLOR = {"pass": "#1a7f4b", "review": "#b26a00", "quarantine": "#b3261e", "block": "#8c1d18"}
_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#14181f;--mut:#5b6472;--line:#dde1e8;--card:#f6f7f9}
@media(prefers-color-scheme:dark){:root{--bg:#0f1218;--fg:#e8ebf0;--mut:#9aa3b2;--line:#2a3140;--card:#171c25}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:32px 20px}
main{max-width:920px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.badge{display:inline-block;color:#fff;border-radius:6px;padding:2px 10px;font-weight:700;text-transform:uppercase;font-size:13px}
.mut{color:var(--mut)}table{width:100%;border-collapse:collapse;font-size:13.5px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}code{font-size:12.5px;word-break:break-all}
"""


def _kv(rows: list[tuple[str, Any]]) -> str:
    return "<table>" + "".join(f"<tr><th style='width:30%'>{e(str(k))}</th><td>{e(str(v if v not in (None, '') else '-'))}</td></tr>"
                               for k, v in rows) + "</table>"


def render_html(r: dict[str, Any]) -> str:
    d, run = r["decision"], r["run"]
    color = _COLOR.get(d["decision"], "#444")
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>AIDAP report {e(run['id'])}</title><style>{_CSS}</style></head><body><main>",
           f"<p class='mut'>AIDAP assurance report · {e(r['generated_at'])}</p>",
           f"<h1>{e(run.get('filename') or run.get('label') or run['id'])}</h1>",
           f"<p><span class='badge' style='background:{color}'>{e(d['decision'])}</span> "
           f"<span class='mut'>status {e(d['status'])} · disposition {e(d['disposition'])} · "
           f"release {'authorised' if d['release_authorized'] else 'not authorised'}"
           f"{' · SHADOW (advisory only)' if d['shadow'] else ''}</span></p>",
           f"<div class='card'><strong>{e(d['summary'])}</strong><br><span class='mut'>{e(d['next_action'])}</span></div>",
           "<h2>Run</h2>", _kv([("Run", run["id"]), ("Project", run.get("project_name") or run.get("project_id")),
                                ("Profile", d["profile_ref"]), ("Policy", d["policy_ref"]), ("Submitted by", run.get("created_by")),
                                ("Submitted", run.get("created_at")), ("Input digest", d["input_digest"]),
                                ("Valid until", d.get("expires_at")), ("Decided by", d["decided_by"])]),
           "<h2>Reasons</h2>"]
    if d["reasons"]:
        out.append("<table><tr><th>Code</th><th>Effect</th><th>Message</th><th>Waived</th></tr>" + "".join(
            f"<tr><td><code>{e(x['code'])}</code></td><td>{e(x['effect'])}</td><td>{e(x['message'])}<br><span class='mut'>{e(x.get('guidance', ''))}</span></td>"
            f"<td>{e(x.get('waived_by') or '-')}</td></tr>" for x in d["reasons"]) + "</table>")
    else:
        out.append("<p class='mut'>No blocking or reviewable reasons.</p>")
    cov = r["coverage"]
    out.append("<h2>Coverage</h2><p class='mut'>Mandatory checks resolved: "
               f"{e(str(cov.get('mandatory_resolved', cov.get('mandatory_ok', '-'))))} / {e(str(cov.get('mandatory_total', '-')))}"
               + (f" · unresolved: {e(', '.join(cov['unresolved_checks']))}" if cov.get("unresolved_checks") else "") + "</p>")
    out.append("<table><tr><th>Check</th><th>Status</th><th>Origin</th><th>Coverage</th><th>Findings</th></tr>" + "".join(
        f"<tr><td><code>{e(c['check_id'])}</code>{' *' if c['mandatory'] else ''}</td><td>{e(c['status'])}</td><td>{e(c['origin'])}</td>"
        f"<td>{'-' if c['coverage'] is None else e(str(round(c['coverage'] * 100)) + '%')}</td><td>{c['findings']}</td></tr>"
        for c in r["checks"]) + "</table><p class='mut'>* mandatory under the policy</p>")
    out.append(f"<h2>Findings ({len(r['findings'])})</h2>")
    for f in r["findings"][:300]:
        conf = f.get("confidence") or {}
        out.append(f"<div class='card'><strong>{e(f['title'])}</strong> <span class='mut'>· {e(f['severity'])} · <code>{e(f['code'])}</code> · "
                   f"{e(conf.get('basis', ''))} · {e(f.get('origin', ''))}</span><br>"
                   f"<b>Observed:</b> {e(f['observed'])}<br><b>Inference:</b> {e(f['inference'])}<br>"
                   f"<b>Recommended:</b> {e(f['recommended_action'])}</div>")
    if r["exceptions"]:
        out.append("<h2>Exceptions</h2><table><tr><th>Id</th><th>Codes</th><th>Granted by</th><th>Justification</th><th>Expires</th></tr>" + "".join(
            f"<tr><td>{e(x['id'])}</td><td>{e(', '.join(x['reason_codes']))}</td><td>{e(x['granted_by'])} ({e(x['granted_role'])})</td>"
            f"<td>{e(x['justification'])}</td><td>{e(str(x['expires_at']))}{' (revoked)' if x['revoked'] else ''}</td></tr>"
            for x in r["exceptions"]) + "</table>")
    out.append("<h2>Evidence</h2>" + _kv([("Seal (SHA-256)", r["evidence"]["seal"]), ("Bundle", r["evidence"]["bundle_id"])]))
    out.append("<h2>Notes</h2><ul class='mut'>" + "".join(f"<li>{e(n)}</li>" for n in r["notes"]) + "</ul></main></body></html>")
    return "".join(out)
