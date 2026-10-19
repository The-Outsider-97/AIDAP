"""semantic.rules and semantic.conflicts — configured meaning checks.

These are deliberately narrow (whitepaper 7.4.1): profile-configured rules and
simple cross-statement conflicts with both spans cited. General contradiction
or relevance judgement across arbitrary documents is *not* claimed here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ....domain.evaluations import CheckResult, Confidence, Severity, UnknownReason
from ....domain.policies.regex_guard import MAX_SCAN_CHARS, check_regex, compile_safe
from ...normalization.models import iter_text_units
from ..base import EvalContext, error_result, finish, make_finding, pointer

__all__ = ["check_semantic_rules", "check_conflicts"]


def _units(ctx: EvalContext, fields: list[str] | None):
    for u in iter_text_units(ctx.norm):
        if fields and ctx.norm.is_records:
            col = u.path.split(".", 1)[1] if "." in u.path else ""
            if col not in fields:
                continue
        yield u


def check_semantic_rules(ctx: EvalContext) -> CheckResult:
    rules = ctx.profile.semantic_rules
    name = "aidap.semantic.configured_rules"
    if not rules:
        return finish(ctx, "semantic.rules", [], coverage=1.0, metrics={"rules": 0}, name=name,
                      message="No semantic rules configured.")
    findings = []
    covered = 1.0
    for idx, rule in enumerate(rules):
        rid = str(rule.get("id") or f"rule{idx + 1}")
        sev = Severity.parse(rule.get("severity"), Severity.MEDIUM)
        msg = str(rule.get("message") or rid)
        fields = rule.get("fields") or ctx.profile.text_fields or None
        if "label_leakage" in rule and ctx.norm.is_records:
            spec = rule["label_leakage"]
            label = spec.get("label")
            feats = spec.get("features") or [c for c in ctx.norm.columns if c != label]
            recs = ctx.norm.records or []
            for f in feats:
                pairs = [(r.get(f), r.get(label)) for r in recs if r.get(f) not in (None, "") and r.get(label) not in (None, "")]
                if len(pairs) >= 20:
                    same = sum(1 for a, b in pairs if str(a) == str(b)) / len(pairs)
                    if same >= 0.99:
                        findings.append(make_finding(
                            "semantic.rules", f"semantic.rules.label_leakage", f"Possible label leakage: {f}", Severity.HIGH,
                            f"'{f}' equals the label '{label}' in {same:.1%} of rows",
                            "A feature that restates the label lets a model memorise the answer.",
                            Confidence.heuristic(round(same, 3), "exact equality rate"),
                            "Remove the feature or confirm it is available at prediction time.",
                            data={"feature": f, "label": label, "rule": rid}))
            continue
        for kind in ("forbid_regex", "forbid_phrase", "require_regex", "require_phrase"):
            if kind not in rule:
                continue
            raw = str(rule[kind])
            if kind.endswith("regex"):
                reason = check_regex(raw)
                if reason:
                    return error_result(ctx, "semantic.rules", UnknownReason.NOT_CONFIGURED,
                                        f"Rule '{rid}' has an unsafe pattern: {reason}", name=name)
                rx = compile_safe(raw)
            else:
                rx = re.compile(re.escape(raw), re.IGNORECASE)
            hits: list[tuple[str, str, int, int]] = []
            scanned = total = 0
            for u in _units(ctx, fields):
                total += len(u.text)
                if scanned >= MAX_SCAN_CHARS:
                    continue
                piece = u.text[: MAX_SCAN_CHARS - scanned]
                scanned += len(piece)
                for m in rx.finditer(piece):
                    hits.append((u.path, piece, m.start(), m.end()))
                    if len(hits) > 500:
                        break
            if total:
                covered = min(covered, scanned / total)
            if kind.startswith("forbid") and hits:
                findings.append(make_finding(
                    "semantic.rules", f"semantic.rules.{rid}", msg, sev,
                    f"{len(hits)} match(es) of the forbidden {'pattern' if kind.endswith('regex') else 'phrase'} in rule '{rid}'",
                    "The content contains text the profile prohibits for this use.", Confidence.deterministic(),
                    "Remove or rewrite the matching content.",
                    pointers=[pointer(p, t, a, b) for p, t, a, b in hits[:5]], count=len(hits), data={"rule": rid}))
            elif kind.startswith("require") and not hits:
                findings.append(make_finding(
                    "semantic.rules", f"semantic.rules.{rid}", msg, sev,
                    f"Required {'pattern' if kind.endswith('regex') else 'phrase'} of rule '{rid}' was not found",
                    "The content lacks text the profile requires for this use.", Confidence.deterministic(),
                    "Add the required text.", data={"rule": rid}))
    return finish(ctx, "semantic.rules", findings, coverage=covered, metrics={"rules": len(rules)}, name=name)


_KV = re.compile(r"^\s*(?:[-*]\s+)?\**([A-Za-z][A-Za-z0-9 _/-]{1,48}?)\**\s*[:=]\s*(.{1,160}?)\s*$")
_TABLE = re.compile(r"^\s*\|\s*([^|]{2,48}?)\s*\|\s*([^|]{1,120}?)\s*\|\s*$")
_QUANT = re.compile(r"\b((?:the )?[A-Za-z][A-Za-z ]{2,40}?)\s+(?:is|are|=|of)\s+(\d+(?:[.,]\d+)?)\s*(%|[A-Za-z]{1,12})?", re.IGNORECASE)


def check_conflicts(ctx: EvalContext) -> CheckResult:
    name = "aidap.semantic.conflicts"
    findings = []
    n = ctx.norm
    if n.is_records:
        key = ctx.profile.thresholds.get("conflict_key")
        if not key:
            return finish(ctx, "semantic.conflicts", [], coverage=1.0, name=name,
                          message="No conflict_key configured for record inputs.")
        groups: dict[str, list[int]] = defaultdict(list)
        recs = n.records or []
        for i, r in enumerate(recs):
            if r.get(key) not in (None, ""):
                groups[str(r[key])].append(i)
        for k, rows in groups.items():
            if len(rows) < 2:
                continue
            diff = [c for c in n.columns if c != key and len({str(recs[i].get(c)) for i in rows}) > 1]
            if diff:
                findings.append(make_finding(
                    "semantic.conflicts", "semantic.conflicts.records", f"Conflicting records for {key}={k}",
                    Severity.MEDIUM, f"{len(rows)} records share {key}={k} but differ in: {', '.join(diff[:6])}",
                    "The same entity is described with different values.", Confidence.deterministic(),
                    "Keep one authoritative record per key.", pointers=[pointer(f"records[{i}]") for i in rows[:4]],
                    count=len(rows), data={"key": k, "fields": diff[:10]}))
                if len(findings) >= 25:
                    break
        return finish(ctx, "semantic.conflicts", findings, coverage=n.parse.coverage, name=name)
    text = n.text
    kv: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        m = _KV.match(stripped) or _TABLE.match(stripped)
        if m:
            k = re.sub(r"\s+", " ", m.group(1).strip().lower())
            v = m.group(2).strip().lower()
            kv[k].append((v, pos + m.start(2), pos + m.end(2), "kv"))
        pos += len(line)
    quant: dict[tuple[str, str], list[tuple[str, int, int]]] = defaultdict(list)
    for m in _QUANT.finditer(text[:2_000_000]):
        subject = re.sub(r"^(the )", "", re.sub(r"\s+", " ", m.group(1).strip().lower()))
        quant[(subject, (m.group(3) or "").lower())].append((m.group(2).replace(",", "."), m.start(2), m.end(2)))
    for k, items in kv.items():
        values = {v for v, *_ in items}
        if len(values) > 1:
            findings.append(make_finding(
                "semantic.conflicts", "semantic.conflicts.statement", f"Conflicting values for '{k}'", Severity.MEDIUM,
                f"'{k}' is given {len(values)} different values",
                "The same attribute is stated differently in two places in this input.", Confidence.heuristic(None, "key-value match"),
                "Decide which value is authoritative.",
                pointers=[pointer("text", text, a, b) for _, a, b, _ in items[:2]], count=len(items), data={"key": k}))
    for (subject, unit), items in quant.items():
        values = {v for v, *_ in items}
        if len(values) > 1 and len(subject) > 3:
            findings.append(make_finding(
                "semantic.conflicts", "semantic.conflicts.quantity", f"Conflicting quantities for '{subject}'",
                Severity.MEDIUM, f"'{subject}' is stated as {', '.join(sorted(values)[:3])} {unit}",
                "Two statements give different numbers for what appears to be the same quantity.",
                Confidence.heuristic(None, "sentence pattern; may describe different cases"),
                "Check whether these describe the same thing and reconcile them.",
                pointers=[pointer("text", text, a, b) for _, a, b in items[:2]], count=len(items),
                data={"subject": subject}))
    return finish(ctx, "semantic.conflicts", findings[:25], coverage=n.parse.coverage, name=name)
