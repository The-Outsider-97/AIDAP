"""Upstream monitoring signals: results that data-quality and observability tools already produced about an input.

AIDAP consumes these (whitepaper 7.11: "consume monitoring signals; focus on admission decisions") and never replaces
the tools that produce them. A signal is *asserted by the submitter*; it can add findings but never removes one.

Accepted shapes (all under source metadata):
  upstream_checks: [{"source": "monte_carlo", "name": "orders_freshness", "status": "failed", "observed_at": "...",
                     "url": "https://..."}]
  great_expectations_result: a GX validation result object (``success``, ``statistics``, ``meta``)
  soda_scan: a Soda scan summary (``hasFailures``, ``hasErrors``, ``hasWarnings``)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

__all__ = ["collect_signals", "STATUSES", "MAX_SIGNALS"]

STATUSES = ("passed", "warning", "failed", "unknown")
MAX_SIGNALS = 50
_ALIAS = {"passed": "passed", "pass": "passed", "ok": "passed", "success": "passed", "succeeded": "passed", "green": "passed",
          "warn": "warning", "warning": "warning", "yellow": "warning",
          "fail": "failed", "failed": "failed", "failure": "failed", "error": "failed", "red": "failed",
          "critical": "failed", "breached": "failed"}


def _status(v: Any) -> str:
    if isinstance(v, bool):
        return "passed" if v else "failed"
    return _ALIAS.get(str(v).strip().lower(), "unknown")


def _when(v: Any) -> str | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()


def _gx(doc: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(doc, dict) or "success" not in doc:
        return None
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    stats = doc.get("statistics") if isinstance(doc.get("statistics"), dict) else {}
    run_id = meta.get("run_id") if isinstance(meta.get("run_id"), dict) else {}
    name = meta.get("expectation_suite_name") or meta.get("suite_name") or "validation"
    st = "passed" if doc.get("success") else "failed"
    return {"source": "great_expectations", "name": str(name)[:80], "status": st,
            "observed_at": _when(run_id.get("run_time")),
            "detail": f"{stats.get('unsuccessful_expectations', '?')} of {stats.get('evaluated_expectations', '?')} "
                      f"expectations unsuccessful"[:120] if st == "failed" else ""}


def _soda(doc: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(doc, dict) or not ({"hasFailures", "hasErrors", "hasWarnings"} & set(doc)):
        return None
    st = "failed" if (doc.get("hasFailures") or doc.get("hasErrors")) else "warning" if doc.get("hasWarnings") else "passed"
    return {"source": "soda", "name": str(doc.get("dataSource") or doc.get("name") or "scan")[:80], "status": st,
            "observed_at": _when(doc.get("scanEndTimestamp")), "detail": ""}


def collect_signals(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise every supported shape to ``{source, name, status, observed_at, detail, url}``; ignore malformed items."""
    out: list[dict[str, Any]] = []
    raw = meta.get("upstream_checks")
    for item in (raw if isinstance(raw, list) else [])[:MAX_SIGNALS]:
        if not isinstance(item, dict):
            continue
        out.append({"source": str(item.get("source") or "unspecified")[:60], "name": str(item.get("name") or "check")[:80],
                    "status": _status(item.get("status")), "observed_at": _when(item.get("observed_at")),
                    "detail": str(item.get("detail") or "")[:120], "url": str(item.get("url") or "")[:300]})
    for key, fn in (("great_expectations_result", _gx), ("soda_scan", _soda)):
        if key in meta:
            sig = fn(meta[key])
            if sig:
                out.append({**sig, "url": ""})
    return out[:MAX_SIGNALS]
