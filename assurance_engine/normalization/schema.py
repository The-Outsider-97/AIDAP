"""Lightweight schema inference used for baselines and drift."""

from __future__ import annotations

import re
from typing import Any

from ...domain.utils.domain_helpers import canonical_digest, parse_date_lenient

__all__ = ["infer_type", "infer_schema", "schema_signature"]

_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def infer_type(value: Any) -> str:
    if value is None or value == "":
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (dict, list)):
        return "object"
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in ("true", "false"):
            return "boolean"
        if re.fullmatch(r"[+-]?\d+", s) and len(s) < 16:
            return "integer"
        if _NUM.match(s) and len(s) < 32:
            return "number"
        if len(s) <= 40 and parse_date_lenient(s) is not None and re.search(r"\d{4}|\d{2}[-/]\d{2}", s):
            return "date"
        return "string"
    return "string"


def infer_schema(records: list[dict[str, Any]], columns: list[str], sample: int = 5000) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    sub = records[:sample]
    for col in columns:
        counts: dict[str, int] = {}
        for r in sub:
            t = infer_type(r.get(col))
            counts[t] = counts.get(t, 0) + 1
        non_null = {k: v for k, v in counts.items() if k != "null"}
        if not non_null:
            dominant = "null"
        elif set(non_null) <= {"integer", "number"}:
            dominant = "number" if "number" in non_null else "integer"
        else:
            dominant = max(non_null, key=lambda k: non_null[k])
        out[col] = {"type": dominant, "nullable": counts.get("null", 0) > 0}
    return out


def schema_signature(schema: dict[str, dict[str, Any]]) -> str:
    return canonical_digest({k: v["type"] for k, v in sorted(schema.items())})
