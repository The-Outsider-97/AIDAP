"""quality.relationship — configured cross-field dependencies and reference keys."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ....domain.evaluations import CheckResult, Confidence, Severity, UnknownReason
from ....domain.utils.domain_helpers import parse_date_lenient
from ..base import EvalContext, finish, make_finding, not_evaluated, pointer

__all__ = ["check_relationship"]


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _cmp(a: Any, b: Any, op: str) -> bool | None:
    da, db = parse_date_lenient(a), parse_date_lenient(b)
    if da is not None and db is not None:
        a, b = da, db
    else:
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            return None
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}.get(op)


def check_relationship(ctx: EvalContext) -> CheckResult:
    rels = ctx.profile.relationships
    name = "aidap.quality.relationships"
    if not rels:
        return finish(ctx, "quality.relationship", [], coverage=1.0, metrics={"rules": 0}, name=name,
                      message="No relationship rules configured.")
    if not ctx.norm.is_records:
        return not_evaluated(ctx, "quality.relationship", UnknownReason.NOT_APPLICABLE,
                             "Relationship rules apply to record-based inputs.", name=name)
    recs = ctx.norm.records or []
    findings = []
    for idx, rule in enumerate(rels):
        rid = rule.get("id") or f"rel{idx + 1}"
        if "unique" in rule:
            fields = rule["unique"] if isinstance(rule["unique"], list) else [rule["unique"]]
            seen: dict[tuple, int] = {}
            dup: list[int] = []
            for i, r in enumerate(recs):
                key = tuple(str(r.get(f)) for f in fields)
                if any(_empty(r.get(f)) for f in fields):
                    continue
                if key in seen:
                    dup.append(i)
                else:
                    seen[key] = i
            if dup:
                findings.append(make_finding(
                    "quality.relationship", "quality.relationship.not_unique", f"Duplicate key: {', '.join(fields)}",
                    Severity.HIGH, f"{len(dup)} record(s) repeat an existing key ({', '.join(fields)})",
                    "The declared key is not unique.", Confidence.deterministic(),
                    "Make the key unique or remove the duplicates.", pointers=[pointer(f"records[{i}]") for i in dup[:5]],
                    count=len(dup), data={"rule": rid, "fields": fields}))
        elif "if_field" in rule:
            f, eq, req = rule["if_field"], rule.get("equals"), rule.get("require")
            bad = [i for i, r in enumerate(recs) if str(r.get(f)) == str(eq) and _empty(r.get(req))]
            if bad:
                findings.append(make_finding(
                    "quality.relationship", "quality.relationship.dependency", f"'{req}' required when {f} = {eq}",
                    Severity.HIGH, f"{len(bad)} record(s) have {f} = {eq} but no '{req}'",
                    "A dependent field required by the profile is missing.", Confidence.deterministic(),
                    f"Populate '{req}' for these records.", pointers=[pointer(f"records[{i}].{req}") for i in bad[:5]],
                    count=len(bad), data={"rule": rid}))
        elif "reference" in rule:
            ref = rule["reference"]
            f, target = ref.get("field"), ref.get("in_field")
            known = {str(r.get(target)) for r in recs if not _empty(r.get(target))}
            bad = [i for i, r in enumerate(recs) if not _empty(r.get(f)) and str(r.get(f)) not in known]
            if bad:
                findings.append(make_finding(
                    "quality.relationship", "quality.relationship.dangling_reference", f"Unresolved reference: {f}",
                    Severity.HIGH, f"{len(bad)} value(s) of '{f}' do not appear in '{target}'",
                    "Reference keys must resolve within the batch.", Confidence.deterministic(),
                    "Include the referenced records or correct the keys.",
                    pointers=[pointer(f"records[{i}].{f}") for i in bad[:5]], count=len(bad), data={"rule": rid}))
        elif "compare" in rule:
            c = rule["compare"]
            left, op, right = c.get("left"), c.get("op", "<="), c.get("right")
            bad = []
            for i, r in enumerate(recs):
                if _empty(r.get(left)) or _empty(r.get(right)):
                    continue
                res = _cmp(r.get(left), r.get(right), op)
                if res is False:
                    bad.append(i)
            if bad:
                findings.append(make_finding(
                    "quality.relationship", "quality.relationship.comparison", f"{left} {op} {right} violated",
                    Severity.HIGH, f"{len(bad)} record(s) violate {left} {op} {right}",
                    "Two fields contradict a configured ordering.", Confidence.deterministic(),
                    "Correct the values.", pointers=[pointer(f"records[{i}]") for i in bad[:5]], count=len(bad),
                    data={"rule": rid}))
    return finish(ctx, "quality.relationship", findings, coverage=ctx.norm.parse.coverage,
                  metrics={"rules": len(rels)}, name=name)
