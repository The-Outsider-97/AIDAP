"""CSV export. Every cell is neutralised against spreadsheet formula injection (leading = + - @ tab CR)."""

from __future__ import annotations

import csv
import io
from typing import Any

__all__ = ["csv_safe", "findings_csv", "rows_csv"]


def csv_safe(value: Any) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def rows_csv(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([csv_safe(h) for h in header])
    for r in rows:
        w.writerow([csv_safe(c) for c in r])
    return buf.getvalue()


def findings_csv(report: dict[str, Any]) -> str:
    header = ["severity", "code", "check", "category", "title", "observed", "inference", "confidence_basis", "confidence_interpretation", "count",
              "origin", "recommended_action", "locations"]
    rows = []
    for f in report["findings"]:
        conf = f.get("confidence") or {}
        rows.append([f["severity"], f["code"], f["check_id"], f["category"], f["title"], f["observed"], f["inference"],
                     conf.get("basis", ""), conf.get("interpretation", ""), f.get("count", 1), f.get("origin", ""),
                     f["recommended_action"], "; ".join(p.get("path", "") for p in f.get("pointers", [])[:5])])
    return rows_csv(header, rows)
