"""intake.format, quality.structural and quality.metadata."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ....domain.evaluations import CheckResult, Confidence, Severity
from ....domain.policies.regex_guard import compile_safe
from ....domain.utils.domain_helpers import parse_date_lenient
from ...ingestion.provenance import ALIASES, lookup
from ..base import EvalContext, finish, make_finding, pointer

__all__ = ["check_format", "check_structural", "check_metadata", "type_ok"]

_INT = re.compile(r"^[+-]?\d{1,18}$")
_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def check_format(ctx: EvalContext) -> CheckResult:
    n = ctx.norm
    p = n.parse
    findings = []
    if n.format == "binary":
        findings.append(make_finding(
            "intake.format", "intake.unsupported_format", "Unsupported file format", Severity.HIGH,
            f"Content is {n.detection.get('binary_label') or 'binary data'}",
            "AIDAP reads text, Markdown, HTML, JSON, JSON Lines, CSV and TSV, and PDF and DOCX when the SLAI Reader is available. It cannot assess other formats.",
            Confidence.deterministic("magic bytes"), "Convert the data to a supported format and resubmit."))
        return finish(ctx, "intake.format", findings, coverage=0.0, name="aidap.intake.format")
    if p.errors:
        findings.append(make_finding(
            "intake.format", "intake.parse_error", "The file could not be parsed completely", Severity.HIGH,
            "; ".join(p.errors[:3]), "Content that does not parse cannot be assessed by any later check.",
            Confidence.deterministic(), "Fix the syntax and resubmit.", data={"errors": p.errors[:5]}))
    if p.coverage < 1.0 and not p.errors:
        findings.append(make_finding(
            "intake.format", "intake.parse_incomplete", "Only part of the input was examined", Severity.MEDIUM,
            f"Parse coverage {p.coverage:.1%}" + (" (truncated at the configured limit)" if p.truncated else "")
            + "".join(f"; {w}" for w in p.warnings if "text layer" in w or "pages were read" in w),
            "Findings describe the examined part only; the rest is unassessed.", Confidence.deterministic(),
            "Submit smaller batches, or raise the limits on a plan that allows it."))
    if p.ragged_rows:
        findings.append(make_finding(
            "intake.format", "intake.ragged_rows", "Rows with an unexpected number of fields", Severity.MEDIUM,
            f"{p.ragged_rows} row(s) differ from the header width", "Misaligned rows shift values into the wrong columns.",
            Confidence.deterministic(), "Check quoting and delimiters in the source export."))
    if not n.text.strip() and not (n.records or []) and not p.errors:
        findings.append(make_finding(
            "intake.format", "intake.empty", "The input is empty", Severity.HIGH,
            "No readable content" + "".join(f"; {w}" for w in p.warnings if "text layer" in w),
            "An empty input cannot be fit for any use.", Confidence.deterministic(),
            "Submit a text-searchable version (run OCR first if this is a scan)." if any("text layer" in w for w in p.warnings)
            else "Submit the intended content."))
    for w in p.warnings:
        if "UTF-8" in w:
            findings.append(make_finding(
                "intake.format", "intake.encoding", "Invalid text encoding", Severity.LOW, w,
                "Some bytes were replaced; original wording may be altered.", Confidence.deterministic(),
                "Re-export the file as UTF-8."))
    return finish(ctx, "intake.format", findings, coverage=p.coverage if not p.errors else 0.0,
                  metrics={"format": n.format, "records": p.records_kept, "isolated": p.isolated},
                  name="aidap.intake.format")


def type_ok(value: Any, typ: str, coerce_strings: bool) -> bool:
    if typ in (None, "", "any"):
        return True
    if value is None:
        return True       # requiredness is a separate rule
    if typ == "string":
        return isinstance(value, str)
    if typ == "boolean":
        return isinstance(value, bool) or (coerce_strings and isinstance(value, str) and value.strip().lower() in ("true", "false"))
    if typ == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return value.is_integer()
        return coerce_strings and isinstance(value, str) and bool(_INT.match(value.strip()))
    if typ == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        return coerce_strings and isinstance(value, str) and bool(_NUM.match(value.strip()))
    if typ == "date":
        return parse_date_lenient(value) is not None
    return True


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and _NUM.match(value.strip()):
        return float(value)
    return None


def check_structural(ctx: EvalContext) -> CheckResult:
    n, prof = ctx.norm, ctx.profile
    findings = []
    metrics: dict[str, Any] = {}
    if n.is_records:
        records = n.records or []
        coerce = n.format in ("csv", "tsv")
        specs = [f for f in prof.fields if f.get("name")]
        if not specs:
            metrics["note"] = "profile declares no field rules"
        cols = set(n.columns)
        agg: dict[tuple[str, str], list[int]] = defaultdict(list)
        coerced = 0
        for spec in specs:
            name = spec["name"]
            if name not in cols and spec.get("required"):
                findings.append(make_finding(
                    "quality.structural", "quality.structural.missing_field", f"Required field '{name}' is missing",
                    Severity.HIGH, f"Column '{name}' is absent from all {len(records)} records",
                    "A required field that is not present cannot be populated by any record.",
                    Confidence.deterministic(), f"Add the '{name}' field to the source export.", data={"field": name}))
                continue
            rx = compile_safe(str(spec["pattern"])) if spec.get("pattern") else None
            domain = spec.get("domain")
            for i, rec in enumerate(records):
                v = rec.get(name)
                empty = v is None or (isinstance(v, str) and v.strip() == "")
                if empty:
                    if spec.get("required"):
                        agg[(name, "required")].append(i)
                    continue
                if not type_ok(v, spec.get("type", "any"), coerce):
                    agg[(name, "type")].append(i)
                    continue
                if coerce and isinstance(v, str) and spec.get("type") in ("number", "integer"):
                    coerced += 1
                if spec.get("type") in ("number", "integer"):
                    x = _num(v)
                    if x is not None:
                        if "min" in spec and x < float(spec["min"]):
                            agg[(name, "range")].append(i)
                        elif "max" in spec and x > float(spec["max"]):
                            agg[(name, "range")].append(i)
                if isinstance(v, str):
                    if "min_length" in spec and len(v) < int(spec["min_length"]):
                        agg[(name, "length")].append(i)
                    elif "max_length" in spec and len(v) > int(spec["max_length"]):
                        agg[(name, "length")].append(i)
                    if rx is not None and len(v) <= 5000 and not rx.search(v):
                        agg[(name, "pattern")].append(i)
                if domain and str(v) not in {str(d) for d in domain}:
                    agg[(name, "domain")].append(i)
        titles = {"required": ("Required value missing", Severity.HIGH),
                  "type": ("Value has the wrong type", Severity.HIGH),
                  "range": ("Value outside the allowed range", Severity.MEDIUM),
                  "length": ("Value length outside limits", Severity.MEDIUM),
                  "pattern": ("Value does not match the required pattern", Severity.MEDIUM),
                  "domain": ("Value outside the allowed set", Severity.MEDIUM)}
        for (name, rule), rows in sorted(agg.items()):
            title, sev = titles[rule]
            findings.append(make_finding(
                "quality.structural", f"quality.structural.{rule}", f"{title}: {name}", sev,
                f"{len(rows)} of {len(records)} record(s) violate the '{rule}' rule for '{name}'",
                "These records do not meet the schema declared by the intended-use profile.",
                Confidence.deterministic(), "Correct or remove the listed records, then resubmit.",
                pointers=[pointer(f"records[{i}].{name}") for i in rows[:5]], count=len(rows),
                data={"field": name, "rule": rule, "rate": round(len(rows) / max(len(records), 1), 4)}))
        if prof.threshold("strict_columns", False) and specs:
            extra = sorted(cols - {s["name"] for s in specs} - {"_extra"})
            if extra:
                findings.append(make_finding(
                    "quality.structural", "quality.structural.unexpected_field", "Unexpected fields", Severity.LOW,
                    f"Fields not in the profile: {', '.join(extra[:10])}", "Undeclared fields are not validated.",
                    Confidence.deterministic(), "Declare the fields in the profile or remove them."))
        min_records = int(prof.threshold("min_records", 1))
        if len(records) < min_records:
            findings.append(make_finding(
                "quality.structural", "quality.structural.too_few_records", "Too few records", Severity.MEDIUM,
                f"{len(records)} record(s); the profile requires at least {min_records}",
                "A small batch may not be representative.", Confidence.deterministic(),
                "Submit a larger batch or lower the minimum in the profile."))
        metrics.update({"records": len(records), "coerced_values": coerced, "rules_checked": len(specs)})
        coverage = n.parse.coverage
    else:
        text = n.text
        min_chars = int(prof.threshold("min_text_chars", 1))
        max_chars = prof.thresholds.get("max_text_chars")
        if len(text.strip()) < min_chars:
            findings.append(make_finding(
                "quality.structural", "quality.structural.too_short", "Text shorter than the profile minimum",
                Severity.HIGH, f"{len(text.strip())} characters; at least {min_chars} required",
                "Too little content to be useful for this task.", Confidence.deterministic(),
                "Provide the full content."))
        if max_chars and len(text) > int(max_chars):
            findings.append(make_finding(
                "quality.structural", "quality.structural.too_long", "Text longer than the profile maximum",
                Severity.MEDIUM, f"{len(text)} characters; at most {int(max_chars)} allowed",
                "Oversized documents are poorly chunked or truncated downstream.", Confidence.deterministic(),
                "Split the document."))
        if text:
            bad = text.count("�")
            if bad / max(len(text), 1) > 0.01:
                findings.append(make_finding(
                    "quality.structural", "quality.structural.encoding_damage", "Damaged characters", Severity.MEDIUM,
                    f"{bad} replacement characters ({bad / len(text):.1%})", "Text was corrupted before submission.",
                    Confidence.deterministic(), "Re-export the source with correct encoding."))
            ctrl = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
            if ctrl / max(len(text), 1) > 0.001:
                findings.append(make_finding(
                    "quality.structural", "quality.structural.control_characters", "Control characters in text",
                    Severity.MEDIUM, f"{ctrl} control characters", "Often indicates binary or damaged content.",
                    Confidence.deterministic(), "Clean the text before submitting."))
        metrics["chars"] = len(text)
        coverage = n.parse.coverage
    return finish(ctx, "quality.structural", findings, coverage=coverage, metrics=metrics,
                  name="aidap.quality.structural")


def check_metadata(ctx: EvalContext) -> CheckResult:
    required = ctx.profile.required_metadata
    findings = []
    missing = []
    for key in required:
        canon = key if key in ALIASES else None
        value = lookup(ctx.source_metadata, canon) if canon else ctx.source_metadata.get(key)
        if value in (None, ""):
            missing.append(key)
    if missing:
        findings.append(make_finding(
            "quality.metadata", "quality.metadata.missing", "Required metadata is missing", Severity.HIGH,
            f"Missing: {', '.join(missing)}", "Without these fields a reviewer cannot establish ownership, age or version.",
            Confidence.deterministic(), "Add the missing metadata when submitting (owner, source revision, effective date...).",
            data={"missing": missing}))
    return finish(ctx, "quality.metadata", findings, coverage=1.0,
                  metrics={"required": list(required), "missing": missing}, name="aidap.quality.metadata")
