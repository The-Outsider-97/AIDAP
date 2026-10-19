"""temporal.freshness and temporal.supersession."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from ....domain.evaluations import CheckResult, Confidence, Severity
from ....domain.utils.domain_helpers import iso, parse_date_lenient
from ...ingestion.provenance import lookup
from ..base import EvalContext, finish, make_finding, pointer

__all__ = ["check_freshness", "check_supersession"]


def _version_key(v: Any) -> tuple | None:
    s = str(v).strip().lower().lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+){0,3}", s):
        return None
    return tuple(int(x) for x in s.split("."))


def check_freshness(ctx: EvalContext) -> CheckResult:
    name = "aidap.temporal.freshness"
    prof, now = ctx.profile, ctx.now
    findings = []
    meta = ctx.source_metadata
    exp = parse_date_lenient(lookup(meta, "expires_at"))
    eff = parse_date_lenient(lookup(meta, "effective_date"))
    window = prof.freshness_days
    if exp is not None and exp < now:
        findings.append(make_finding(
            "temporal.freshness", "temporal.expired", "Content past its expiry date", Severity.HIGH,
            f"Expiry date {iso(exp)[:10]} is {(now - exp).days} day(s) ago",
            "The source declares itself no longer valid.", Confidence.deterministic(),
            "Provide the current version or an approved extension.", data={"expires_at": iso(exp)}))
    if eff is not None and eff > now + timedelta(days=1):
        findings.append(make_finding(
            "temporal.freshness", "temporal.future_dated", "Effective date is in the future", Severity.MEDIUM,
            f"Effective date {iso(eff)[:10]}", "Content not yet in force may be used prematurely.",
            Confidence.deterministic(), "Release it when it takes effect."))
    date_field = prof.thresholds.get("date_field")
    if ctx.norm.is_records and date_field and window:
        recs = ctx.norm.records or []
        dates = [(i, parse_date_lenient(r.get(date_field))) for i, r in enumerate(recs)]
        valid = [(i, d) for i, d in dates if d is not None]
        stale = [i for i, d in valid if (now - d).days > window]
        unparsed = len(recs) - len(valid)
        ratio = len(stale) / max(len(valid), 1)
        limit = float(prof.threshold("max_stale_ratio", 0.1))
        if valid and ratio > limit:
            findings.append(make_finding(
                "temporal.freshness", "temporal.stale_records", f"Stale records by '{date_field}'", Severity.HIGH if ratio > 0.5 else Severity.MEDIUM,
                f"{len(stale)} of {len(valid)} dated records ({ratio:.1%}) are older than {window} days; limit {limit:.0%}",
                "Old records may describe a state of the world that no longer holds.", Confidence.deterministic(),
                "Refresh the stale records.", pointers=[pointer(f"records[{i}].{date_field}") for i in stale[:5]],
                count=len(stale), data={"field": date_field}))
        if unparsed and unparsed / max(len(recs), 1) > 0.1:
            findings.append(make_finding(
                "temporal.freshness", "temporal.undated", f"Records without a usable '{date_field}'", Severity.MEDIUM,
                f"{unparsed} of {len(recs)} records have no parsable date", "Freshness cannot be assessed for them.",
                Confidence.deterministic(), "Provide dates for all records."))
    elif window:
        if eff is None:
            findings.append(make_finding(
                "temporal.freshness", "temporal.undated", "No date to assess freshness", Severity.MEDIUM,
                f"The profile requires content no older than {window} days, but no effective date is declared",
                "Freshness cannot be established, so it is not assumed.", Confidence.deterministic(),
                "Declare the effective date (effective_date, published, updated...)."))
        elif (now - eff).days > window:
            findings.append(make_finding(
                "temporal.freshness", "temporal.stale", "Content older than the freshness window", Severity.HIGH,
                f"Effective date {iso(eff)[:10]} is {(now - eff).days} days old; the window is {window} days",
                "Content past the window may be outdated for this use.", Confidence.deterministic(),
                "Provide a current version or have an owner confirm it is still valid.",
                data={"age_days": (now - eff).days, "window": window}))
    return finish(ctx, "temporal.freshness", findings, coverage=1.0,
                  metrics={"effective_date": iso(eff), "expires_at": iso(exp), "window_days": window}, name=name)


_MARKERS = re.compile(r"\b(?:this (?:document|policy|manual|page) (?:has been|is) (?:superseded|replaced|withdrawn|deprecated)|"
                      r"no longer (?:valid|supported|in force|maintained)|obsolete|do not use)\b", re.IGNORECASE)


def check_supersession(ctx: EvalContext) -> CheckResult:
    name = "aidap.temporal.supersession"
    meta = ctx.source_metadata
    findings = []
    by = lookup(meta, "superseded_by")
    if by:
        findings.append(make_finding(
            "temporal.supersession", "temporal.superseded", "Declared as superseded", Severity.HIGH,
            f"Metadata says this content is superseded by '{by}'", "A newer revision should be used instead.",
            Confidence.deterministic(), "Submit the replacing revision.", data={"superseded_by": str(by)}))
    rev = lookup(meta, "source_revision")
    mine = _version_key(rev) if rev is not None else None
    digest = ctx.norm.original_digest
    for known in ctx.known_revisions:
        k = _version_key(known.get("revision"))
        if mine is not None and k is not None and k > mine:
            findings.append(make_finding(
                "temporal.supersession", "temporal.superseded", "A newer approved revision already exists", Severity.HIGH,
                f"Revision {rev} submitted; revision {known.get('revision')} was already approved",
                "Older revisions should not replace newer approved content.", Confidence.deterministic(),
                "Submit the newest revision.", data={"newer": str(known.get("revision")), "version_id": known.get("version_id")}))
            break
        if mine is not None and k == mine and known.get("digest") and known["digest"] != digest:
            findings.append(make_finding(
                "temporal.supersession", "temporal.revision_conflict", "Same revision number, different content",
                Severity.MEDIUM, f"Revision {rev} was approved earlier with different content",
                "A revision number should identify one content.", Confidence.deterministic(),
                "Increment the revision or confirm the change is a correction."))
            break
    head = ctx.norm.text[:3000]
    m = _MARKERS.search(head)
    if m:
        findings.append(make_finding(
            "temporal.supersession", "temporal.superseded_marker", "Text says it is superseded or obsolete", Severity.MEDIUM,
            "A superseded/obsolete notice appears near the start of the content",
            "The wording suggests the content should no longer be used.", Confidence.heuristic(None, "phrase match"),
            "Confirm whether the content is current.", pointers=[pointer("text", head, m.start(), m.end())]))
    return finish(ctx, "temporal.supersession", findings, coverage=1.0,
                  metrics={"known_revisions": len(ctx.known_revisions)}, name=name)
