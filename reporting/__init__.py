"""Report building and rendering (JSON / CSV / HTML / PDF). Pure functions over stored records."""

from __future__ import annotations

import json
from typing import Any

from .builder import REPORT_NOTES, build_report
from .csv_export import csv_safe, findings_csv, rows_csv
from .html_export import render_html
from .pdf_export import render_pdf

__all__ = ["build_report", "render", "render_html", "render_pdf", "findings_csv", "csv_safe", "rows_csv", "REPORT_NOTES",
           "FORMATS"]

FORMATS = {"json": "application/json", "csv": "text/csv; charset=utf-8", "html": "text/html; charset=utf-8",
           "pdf": "application/pdf"}


def render(report: dict[str, Any], fmt: str) -> tuple[bytes, str, str]:
    """Return ``(body, content_type, extension)``."""
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(report, indent=2, ensure_ascii=False, default=str).encode("utf-8"), FORMATS[fmt], "json"
    if fmt == "csv":
        return findings_csv(report).encode("utf-8"), FORMATS[fmt], "csv"
    if fmt == "html":
        return render_html(report).encode("utf-8"), FORMATS[fmt], "html"
    if fmt == "pdf":
        return render_pdf(report), FORMATS[fmt], "pdf"
    raise ValueError(f"unsupported report format {fmt!r}")
