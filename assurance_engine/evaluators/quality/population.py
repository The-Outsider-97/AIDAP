"""quality.duplicates, quality.statistical, quality.anomaly and baseline statistics.

Statistical unusualness is not a defect (whitepaper 7.2): observation,
interpretation and policy consequence are kept apart. Drift is only assessed
against an *approved* baseline; the first batch is never trusted implicitly.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from ....domain.evaluations import CheckResult, Confidence, Severity, UnknownReason
from ...normalization.models import NormalizedInput
from ...normalization.schema import infer_schema, schema_signature
from ..base import EvalContext, finish, make_finding, not_evaluated, pointer, unknown
from .similarity import near_duplicates

__all__ = ["check_duplicates", "check_statistical", "check_anomaly", "build_baseline_stats", "BASELINE_SCHEMA"]

BASELINE_SCHEMA = "aidap.baseline/1"
_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_WS = re.compile(r"\s+")


def _as_float(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v, str) and _NUM.match(v.strip()):
        try:
            x = float(v)
            return x if math.isfinite(x) else None
        except ValueError:
            return None
    return None


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def column_stats(records: list[dict[str, Any]], col: str, ctype: str) -> dict[str, Any]:
    n = len(records)
    vals = [r.get(col) for r in records]
    miss = sum(1 for v in vals if _missing(v))
    out: dict[str, Any] = {"type": ctype, "n": n, "missing_rate": round(miss / n, 6) if n else 0.0}
    present = [v for v in vals if not _missing(v)]
    if ctype in ("integer", "number"):
        nums = sorted(x for x in (_as_float(v) for v in present) if x is not None)
        if nums:
            mean = sum(nums) / len(nums)
            var = sum((x - mean) ** 2 for x in nums) / max(len(nums) - 1, 1)
            out.update({"mean": mean, "std": math.sqrt(var), "min": nums[0], "max": nums[-1],
                        "p01": _quantile(nums, 0.01), "p05": _quantile(nums, 0.05),
                        "p95": _quantile(nums, 0.95), "p99": _quantile(nums, 0.99), "count": len(nums)})
    else:
        cnt = Counter(str(v)[:80] for v in present)
        out["distinct"] = len(cnt)
        total = sum(cnt.values()) or 1
        out["categories"] = {k: round(c / total, 6) for k, c in cnt.most_common(50)} if len(cnt) <= 200 else {}
    return out


def build_baseline_stats(norm: NormalizedInput) -> dict[str, Any]:
    """Statistics for a *proposed* baseline. Never auto-approved."""
    records = norm.records or []
    schema = infer_schema(records, norm.columns)
    cols = {c: column_stats(records, c, schema[c]["type"]) for c in norm.columns}
    return {"schema": BASELINE_SCHEMA, "sample_size": len(records), "columns": cols,
            "schema_signature": schema_signature(schema)}


# ---------------------------------------------------------------------------------------------------------
def check_duplicates(ctx: EvalContext) -> CheckResult:
    n, prof = ctx.norm, ctx.profile
    thr = float(prof.threshold("max_duplicate_ratio", 0.05))
    findings = []
    metrics: dict[str, Any] = {}
    if n.is_records:
        records = n.records or []
        seen: dict[str, int] = {}
        dups: list[int] = []
        for i, r in enumerate(records):
            key = json.dumps(r, sort_keys=True, default=str)
            if key in seen:
                dups.append(i)
            else:
                seen[key] = i
        ratio = len(dups) / len(records) if records else 0.0
        metrics = {"records": len(records), "duplicates": len(dups), "ratio": round(ratio, 6)}
        if dups and ratio > thr:
            findings.append(make_finding(
                "quality.duplicates", "quality.duplicates.records", "Duplicate records", Severity.HIGH if ratio > 0.5 else Severity.MEDIUM,
                f"{len(dups)} of {len(records)} records ({ratio:.1%}) are exact duplicates; threshold {thr:.1%}",
                "Duplicates over-weight some content and inflate counts.", Confidence.deterministic(),
                "Deduplicate before submitting, or raise max_duplicate_ratio if repetition is intended.",
                pointers=[pointer(f"records[{i}]") for i in dups[:5]], count=len(dups), data=metrics))
        findings.extend(_near_findings(
            [_record_text(r, prof.text_fields) for r in records], set(dups), prof, metrics,
            lambda i: pointer(f"records[{i}]"), "records"))
    else:
        paras = [p for p in re.split(r"\n\s*\n", n.text) if len(p.strip()) >= 40]
        seen_p: set[str] = set()
        dup_n = 0
        examples = []
        for p in paras:
            key = _WS.sub(" ", p.strip().lower())
            if key in seen_p:
                dup_n += 1
                if len(examples) < 5:
                    examples.append(p.strip()[:60])
            else:
                seen_p.add(key)
        ratio = dup_n / len(paras) if paras else 0.0
        metrics = {"paragraphs": len(paras), "duplicates": dup_n, "ratio": round(ratio, 6)}
        if dup_n and ratio > thr:
            findings.append(make_finding(
                "quality.duplicates", "quality.duplicates.passages", "Repeated passages", Severity.MEDIUM,
                f"{dup_n} of {len(paras)} substantial paragraphs ({ratio:.1%}) repeat earlier text; threshold {thr:.1%}",
                "Repeated passages over-weight content in retrieval.", Confidence.deterministic(),
                "Remove repeated sections.", count=dup_n, data=metrics))
        findings.extend(_near_findings(paras, set(), prof, metrics, lambda i: pointer(f"paragraphs[{i}]"), "paragraphs"))
    return finish(ctx, "quality.duplicates", findings, coverage=n.parse.coverage, metrics=metrics,
                  name="aidap.quality.duplicates")


def _record_text(rec: dict[str, Any], text_fields: list[str]) -> str:
    keys = [k for k in text_fields if k in rec] or list(rec)
    return " ".join(str(rec[k]) for k in keys if isinstance(rec.get(k), (str, int, float)) and not isinstance(rec.get(k), bool))


def _near_findings(units: list[str], exact: set[int], prof: Any, metrics: dict[str, Any], ptr: Any, noun: str) -> list:
    """Near-duplicates (word-trigram Jaccard) that are not exact repeats. A similarity observation only."""
    if len(units) < 5:
        return []
    thr = float(prof.threshold("max_near_duplicate_ratio", 0.1))
    found = near_duplicates(units, threshold=float(prof.threshold("near_duplicate_similarity", 0.8)),
                            min_tokens=int(prof.threshold("near_duplicate_min_words", 12)))
    near = {i: v for i, v in found.items() if i not in exact}
    ratio = len(near) / len(units)
    metrics.update({"near_duplicates": len(near), "near_duplicate_ratio": round(ratio, 6)})
    if not near or ratio <= thr:
        return []
    idx = sorted(near)
    return [make_finding(
        "quality.duplicates", "quality.duplicates.near", f"Near-duplicate {noun}",
        Severity.HIGH if ratio > 0.5 else Severity.MEDIUM,
        f"{len(near)} of {len(units)} {noun} ({ratio:.1%}) are near-copies of earlier ones; threshold {thr:.1%}",
        "Almost-identical content over-weights one source and can crowd out distinct material.",
        Confidence.heuristic(round(ratio, 3), "word-trigram Jaccard similarity; not a probability"),
        "Keep one version of each near-copy, or raise max_near_duplicate_ratio if repetition is intended.",
        pointers=[ptr(i) for i in idx[:5]], count=len(near),
        data={"pairs": [{"item": i, "similar_to": near[i][0], "similarity": near[i][1]} for i in idx[:10]],
              "ratio": round(ratio, 4)})]


def check_statistical(ctx: EvalContext) -> CheckResult:
    n, prof = ctx.norm, ctx.profile
    if not n.is_records:
        return not_evaluated(ctx, "quality.statistical", UnknownReason.NOT_APPLICABLE,
                             "Population statistics apply to record-based inputs.", name="aidap.quality.statistical")
    records = n.records or []
    thr = float(prof.threshold("max_missing_ratio", 0.2))
    schema = infer_schema(records, n.columns)
    findings = []
    stats = {c: column_stats(records, c, schema[c]["type"]) for c in n.columns}
    for c, st in stats.items():
        if st["missing_rate"] > thr:
            findings.append(make_finding(
                "quality.statistical", "quality.statistical.missingness", f"High missingness: {c}",
                Severity.HIGH if st["missing_rate"] > 0.5 else Severity.MEDIUM,
                f"{st['missing_rate']:.1%} of '{c}' values are empty; threshold {thr:.1%}",
                "Sparse fields weaken downstream use of the column.", Confidence.deterministic(),
                "Fill the field at source or exclude the column.", data={"field": c, "rate": st["missing_rate"]}))
        elif len(records) >= 20 and st.get("distinct") == 1 and st["missing_rate"] == 0:
            findings.append(make_finding(
                "quality.statistical", "quality.statistical.constant", f"Constant column: {c}", Severity.LOW,
                f"Every value of '{c}' is identical", "A constant column carries no information.",
                Confidence.deterministic(), "Confirm the column is needed.", data={"field": c}))
    findings.extend(_outlier_findings(records, stats, prof))
    if 0 < len(records) < 30:
        findings.append(make_finding(
            "quality.statistical", "quality.statistical.small_sample", "Small sample", Severity.INFO,
            f"{len(records)} records", "Rates computed on fewer than 30 records are unstable.",
            Confidence.deterministic(), "Interpret percentages with care."))
    ctx.cache["column_stats"] = stats
    return finish(ctx, "quality.statistical", findings, coverage=n.parse.coverage,
                  metrics={"records": len(records), "columns": len(n.columns)}, name="aidap.quality.statistical")


def _outlier_findings(records: list[dict[str, Any]], stats: dict[str, dict[str, Any]], prof: Any) -> list:
    """Robust outliers (modified z-score from the median and MAD). Unusual is not wrong: INFO, LOW above 5% of values."""
    out = []
    zmax = float(prof.threshold("outlier_z", 5.0))
    for c, st in stats.items():
        if st.get("type") not in ("integer", "number") or st.get("count", 0) < 30:
            continue
        pairs = [(i, x) for i, r in enumerate(records) if (x := _as_float(r.get(c))) is not None]
        vals = sorted(x for _, x in pairs)
        med = _quantile(vals, 0.5)
        mad = _quantile(sorted(abs(x - med) for x in vals), 0.5)
        if mad <= 0:
            continue
        flagged = [i for i, x in pairs if abs(0.6745 * (x - med) / mad) > zmax]
        if not flagged:
            continue
        share = len(flagged) / len(pairs)
        out.append(make_finding(
            "quality.statistical", "quality.statistical.outliers", f"Extreme values: {c}",
            Severity.LOW if share > 0.05 else Severity.INFO,
            f"{len(flagged)} of {len(pairs)} values ({share:.1%}) lie more than {zmax:g} robust deviations from the median",
            "Extreme values are unusual relative to the rest of this batch. They may be valid.",
            Confidence.heuristic(round(share, 3), "modified z-score (median/MAD); not a probability"),
            "Inspect the flagged records; confirm they are real before relying on them.",
            pointers=[pointer(f"records[{i}].{c}") for i in flagged[:5]], count=len(flagged),
            data={"field": c, "median": med, "mad": mad, "share": round(share, 4)}))
    return out


def check_anomaly(ctx: EvalContext) -> CheckResult:
    n, prof = ctx.norm, ctx.profile
    name = "aidap.quality.baseline_comparison"
    if not n.is_records:
        return not_evaluated(ctx, "quality.anomaly", UnknownReason.NOT_APPLICABLE,
                             "Baseline comparison applies to record-based inputs.", name=name)
    base = ctx.baseline
    if not base:
        return unknown(ctx, "quality.anomaly", UnknownReason.NO_BASELINE,
                       "No approved baseline exists for this profile; drift cannot be assessed. "
                       "Propose and approve a baseline from a trusted batch.", name=name)
    records = n.records or []
    min_n = int(prof.threshold("min_baseline_sample", 30))
    if len(records) < min_n or int(base.get("sample_size", 0)) < min_n:
        return unknown(ctx, "quality.anomaly", UnknownReason.INSUFFICIENT_SAMPLE,
                       f"Both the baseline and the batch need at least {min_n} records to compare.", name=name)
    effect_thr = float(prof.threshold("anomaly_effect_size", 0.5))
    tv_thr = float(prof.threshold("anomaly_category_shift", 0.25))
    schema = infer_schema(records, n.columns)
    cur = ctx.cache.get("column_stats") or {c: column_stats(records, c, schema[c]["type"]) for c in n.columns}
    bcols = base.get("columns", {})
    findings = []
    added, removed = sorted(set(cur) - set(bcols)), sorted(set(bcols) - set(cur))
    if added or removed:
        findings.append(make_finding(
            "quality.anomaly", "quality.anomaly.schema_drift", "Columns differ from the approved baseline", Severity.HIGH,
            f"added: {added[:8] or '-'}; removed: {removed[:8] or '-'}",
            "The batch is not comparable to the baseline population in structure.", Confidence.deterministic(),
            "Confirm the schema change is intended and approve a new baseline version.",
            data={"added": added, "removed": removed}))
    for c in sorted(set(cur) & set(bcols)):
        a, b = cur[c], bcols[c]
        if abs(a["missing_rate"] - b.get("missing_rate", 0.0)) > 0.1:
            findings.append(make_finding(
                "quality.anomaly", "quality.anomaly.missingness_shift", f"Missingness changed: {c}", Severity.MEDIUM,
                f"missing {b.get('missing_rate', 0):.1%} in baseline vs {a['missing_rate']:.1%} now",
                "The share of empty values moved noticeably. This may be intended.", Confidence.heuristic(None, "threshold 10 points"),
                "Confirm the change is intended.", data={"field": c}))
        if a.get("mean") is not None and b.get("mean") is not None and b.get("std", 0) > 0:
            d = abs(a["mean"] - b["mean"]) / b["std"]
            se = b["std"] / math.sqrt(max(a.get("count", 1), 1))
            z = abs(a["mean"] - b["mean"]) / se if se > 0 else 0.0
            if d > effect_thr and z > 3.29:   # large effect AND clearly beyond sampling noise
                findings.append(make_finding(
                    "quality.anomaly", "quality.anomaly.mean_shift", f"Distribution shift: {c}", Severity.MEDIUM,
                    f"mean {b['mean']:.4g} (baseline) vs {a['mean']:.4g} (now); effect size {d:.2f}",
                    "The numeric distribution differs from the approved population. Unusual is not necessarily wrong.",
                    Confidence.heuristic(round(d, 3), "standardised mean difference; not a probability"),
                    "Confirm the shift is intended (seasonality, launch, policy change) or investigate the source.",
                    data={"field": c, "effect_size": round(d, 3), "z": round(z, 1)}))
            lo, hi = b.get("p01"), b.get("p99")
            if lo is not None and hi is not None:
                outside = sum(1 for r in records if (x := _as_float(r.get(c))) is not None and (x < lo or x > hi))
                share = outside / max(a.get("count", 1), 1)
                if share > 0.05:
                    findings.append(make_finding(
                        "quality.anomaly", "quality.anomaly.out_of_range_share", f"Many values outside baseline range: {c}",
                        Severity.MEDIUM, f"{share:.1%} of values lie outside the baseline 1st–99th percentile range",
                        "A larger share of extreme values than the baseline implies.",
                        Confidence.heuristic(round(share, 3), "share beyond baseline percentiles"),
                        "Inspect the extreme values.", data={"field": c, "share": round(share, 4)}))
        elif b.get("categories") and a.get("categories"):
            keys = set(a["categories"]) | set(b["categories"])
            tv = 0.5 * sum(abs(a["categories"].get(k, 0.0) - b["categories"].get(k, 0.0)) for k in keys)
            novel = sum(v for k, v in a["categories"].items() if k not in b["categories"])
            if tv > tv_thr or novel > 0.1:
                findings.append(make_finding(
                    "quality.anomaly", "quality.anomaly.category_shift", f"Category mix changed: {c}", Severity.MEDIUM,
                    f"distribution distance {tv:.2f}; {novel:.1%} of values are new categories",
                    "The mix of categories differs from the approved population.",
                    Confidence.heuristic(round(tv, 3), "total variation distance; not a probability"),
                    "Confirm the new categories are valid.", data={"field": c, "distance": round(tv, 3)}))
    return finish(ctx, "quality.anomaly", findings, coverage=n.parse.coverage,
                  metrics={"baseline_id": base.get("id"), "columns_compared": len(set(cur) & set(bcols))}, name=name)
