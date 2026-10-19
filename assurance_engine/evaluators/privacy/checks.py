"""privacy.pii and privacy.destination — local screening that precedes any external call."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ....domain.data.sensitivity import SENSITIVE_TYPES, SensitiveType
from ....domain.evaluations import CheckResult, Confidence, Severity, UnknownReason
from ...normalization.models import iter_text_units
from ..base import EvalContext, finish, make_finding, pointer
from .detectors import Hit, scan_text

__all__ = ["check_pii", "check_destination", "detect_all"]

MAX_TOTAL_CHARS = 25_000_000


def detect_all(ctx: EvalContext) -> tuple[dict[SensitiveType, list[tuple[str, str, Hit]]], int, int]:
    """Scan every text unit once; memoised on the context (shared by both privacy checks and SLAI gating)."""
    cached = ctx.cache.get("pii_scan")
    if cached is not None:
        return cached
    found: dict[SensitiveType, list[tuple[str, str, Hit]]] = defaultdict(list)
    scanned = total = 0
    for unit in iter_text_units(ctx.norm):
        total += len(unit.text)
        if scanned >= MAX_TOTAL_CHARS:
            continue
        scanned += min(len(unit.text), MAX_TOTAL_CHARS - scanned)
        for hit in scan_text(unit.text):
            found[hit.type].append((unit.path, unit.text, hit))
    ctx.cache["pii_scan"] = (found, scanned, total)
    return found, scanned, total


def _conf(hits: list[tuple[str, str, Hit]]) -> Confidence:
    if hits and all(h.validated for _, _, h in hits):
        return Confidence.validated("pattern and checksum/structure validated")
    return Confidence.heuristic(None, "pattern match without independent validation")


def check_pii(ctx: EvalContext) -> CheckResult:
    found, scanned, total = detect_all(ctx)
    allowed = set(ctx.profile.privacy.allowed_types)
    external = ctx.destination.is_external
    findings = []
    counts: dict[str, int] = {}
    for stype, hits in sorted(found.items(), key=lambda kv: kv[0].value):
        spec = SENSITIVE_TYPES[stype]
        counts[stype.value] = len(hits)
        ptrs = [pointer(path, text, h.start, h.end, hide=True) for path, text, h in hits[:5]]
        if spec.is_secret:
            findings.append(make_finding(
                "privacy.pii", f"privacy.secret.{stype.value}", f"{spec.label.capitalize()} found", spec.severity,
                f"{len(hits)} occurrence(s) of a {spec.label}",
                "A credential in an AI input can be disclosed to any consumer of that input.",
                _conf(hits), "Remove the credential and rotate it before it is used anywhere else.",
                pointers=ptrs, count=len(hits), tags=["secret", "non-waivable"], data={"type": stype.value}))
            continue
        permitted = stype.value in allowed and not (external and stype.value in ctx.profile.privacy.external_forbidden_types)
        severity = Severity.INFO if permitted else spec.severity
        findings.append(make_finding(
            "privacy.pii", f"privacy.pii.{stype.value}", f"{spec.label.capitalize()} detected", severity,
            f"{len(hits)} occurrence(s) of a {spec.label}"
            + (" (permitted by the profile)" if permitted else ""),
            "The text matches a detector for personal or restricted data; detection is not proof of identity.",
            _conf(hits),
            "Redact the values or confirm that this profile and destination may process them.",
            pointers=ptrs, count=len(hits), tags=["pii"] + ([] if permitted else ["redactable"]),
            data={"type": stype.value, "permitted": permitted}))
    personal = [t for t in found if not SENSITIVE_TYPES[t].is_secret and t.value not in ("ip_address",)]
    if personal and not ctx.profile.privacy.purpose.strip():
        findings.append(make_finding(
            "privacy.pii", "privacy.pii.purpose_missing", "Personal data without a declared purpose", Severity.MEDIUM,
            f"Personal data types detected: {', '.join(sorted(t.value for t in personal))}; the profile declares no purpose",
            "Processing personal data requires a declared purpose before a reviewer can judge fitness.",
            Confidence.deterministic(), "Declare the purpose in the profile's privacy section, or redact the data.",
            tags=["purpose"]))
    coverage = 1.0 if total == 0 else min(1.0, scanned / total)
    res = finish(ctx, "privacy.pii", findings, coverage=coverage, metrics={"counts": counts, "scanned_chars": scanned},
                 name="aidap.privacy.local_detectors")
    return res


def check_destination(ctx: EvalContext) -> CheckResult:
    found, scanned, total = detect_all(ctx)
    findings = []
    if ctx.destination.is_external:
        forbidden = set(ctx.profile.privacy.external_forbidden_types)
        for stype, hits in sorted(found.items(), key=lambda kv: kv[0].value):
            spec = SENSITIVE_TYPES[stype]
            if spec.is_secret or stype.value not in forbidden:
                continue
            ptrs = [pointer(path, text, h.start, h.end, hide=True) for path, text, h in hits[:3]]
            block = not ctx.profile.privacy.redact_instead_of_block
            code = (f"policy.prohibited_destination.{stype.value}" if block
                    else f"privacy.destination.{stype.value}")
            findings.append(make_finding(
                "privacy.destination", code,
                f"{spec.label.capitalize()} cannot go to a {ctx.destination.value.replace('_', ' ')}",
                Severity.HIGH,
                f"{len(hits)} {spec.label} value(s) in an input destined for an external endpoint",
                "The destination class is more exposed than the profile permits for this data type.",
                _conf(hits),
                "Create a redacted version (it is re-validated as a new input) or choose a local destination.",
                pointers=ptrs, count=len(hits), tags=["redactable", "destination"], data={"type": stype.value}))
    return finish(ctx, "privacy.destination", findings, coverage=1.0 if total == 0 else min(1.0, scanned / total),
                  metrics={"destination": ctx.destination.value, "external": ctx.destination.is_external},
                  name="aidap.privacy.destination_rules")
