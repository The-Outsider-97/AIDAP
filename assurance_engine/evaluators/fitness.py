"""fitness.intended_use, provenance.origin and provenance.upstream."""

from __future__ import annotations

from datetime import datetime, timedelta

from ...domain.data.classification import DataClassification, DestinationClass
from ...domain.evaluations import CheckResult, Confidence, Severity, UnknownReason
from ..ingestion.provenance import lookup
from ..ingestion.signals import collect_signals
from .base import EvalContext, finish, make_finding, not_evaluated

__all__ = ["check_intended_use", "check_origin", "check_upstream"]


def check_intended_use(ctx: EvalContext) -> CheckResult:
    p, dest = ctx.profile, ctx.destination
    findings = []
    if p.destinations and not p.allows_destination(dest):
        findings.append(make_finding(
            "fitness.intended_use", "policy.prohibited_destination.profile", "Destination not permitted by the profile",
            Severity.HIGH, f"Destination class '{dest.value}' is not among: {', '.join(p.destinations)}",
            "The intended-use profile does not permit this release destination.", Confidence.deterministic(),
            "Choose a destination the profile allows, or use a different profile.", tags=["destination"]))
    max_cls = DataClassification.parse(p.max_classification)
    if ctx.classification.rank > max_cls.rank:
        findings.append(make_finding(
            "fitness.intended_use", "fitness.classification_exceeds", "Classification above what the profile allows",
            Severity.HIGH, f"Input is '{ctx.classification.value}'; the profile allows up to '{max_cls.value}'",
            "More sensitive material than this use was designed for.", Confidence.deterministic(),
            "Use a profile designed for this classification."))
    if dest.is_external and ctx.classification.rank >= DataClassification.CONFIDENTIAL.rank:
        findings.append(make_finding(
            "fitness.intended_use", "policy.prohibited_destination.classification",
            "Confidential material cannot go to an external destination", Severity.HIGH,
            f"'{ctx.classification.value}' input with an external destination ('{dest.value}')",
            "Exposure of this classification outside the organisation is prohibited.", Confidence.deterministic(),
            "Use an internal destination.", tags=["destination"]))
    if p.source_classes and ctx.source_class.value not in p.source_classes:
        findings.append(make_finding(
            "fitness.intended_use", "fitness.source_not_permitted", "Source class not permitted for this use",
            Severity.HIGH, f"Source class '{ctx.source_class.value}'; permitted: {', '.join(p.source_classes)}",
            "This profile accepts only the listed kinds of source.", Confidence.deterministic(),
            "Submit content from a permitted source, or use another profile."))
    aud = lookup(ctx.source_metadata, "audience")
    if aud and p.audience:
        aud_set = {a.strip().lower() for a in str(aud).replace(";", ",").split(",") if a.strip()}
        if not aud_set & {a.lower() for a in p.audience}:
            findings.append(make_finding(
                "fitness.intended_use", "fitness.audience_mismatch", "Content audience differs from the profile's audience",
                Severity.MEDIUM, f"Content audience: {', '.join(sorted(aud_set))}; profile audience: {', '.join(p.audience)}",
                "Content written for one audience may be inappropriate for another.", Confidence.deterministic(),
                "Confirm the content may be shown to the profile's audience."))
    return finish(ctx, "fitness.intended_use", findings, coverage=1.0,
                  metrics={"destination": dest.value, "classification": ctx.classification.value,
                           "source_class": ctx.source_class.value}, name="aidap.fitness.intended_use")


def check_origin(ctx: EvalContext) -> CheckResult:
    meta = ctx.source_metadata
    findings = []
    declared = lookup(meta, "sha256")
    if declared:
        d = str(declared).lower().replace("sha256:", "")
        actual = ctx.norm.original_digest.replace("sha256:", "")
        if d != actual:
            findings.append(make_finding(
                "provenance.origin", "provenance.digest_mismatch", "Declared digest does not match the content",
                Severity.CRITICAL, "The submitted SHA-256 differs from the digest of the received bytes",
                "The content changed in transit or the declaration is wrong. A digest proves integrity only.",
                Confidence.deterministic(), "Re-export the file and compare digests at the source."))
    owner, source = lookup(meta, "owner"), lookup(meta, "source_id")
    if not owner and ctx.source_class.value in ("third_party", "unknown", "customer_upload"):
        findings.append(make_finding(
            "provenance.origin", "provenance.no_owner", "No accountable owner declared", Severity.MEDIUM,
            f"Source class '{ctx.source_class.value}' with no owner", "Nobody is identified who can answer for this content.",
            Confidence.deterministic(), "Declare the owner when submitting."))
    if not source:
        findings.append(make_finding(
            "provenance.origin", "provenance.no_source", "No source identifier declared", Severity.LOW,
            "No source URL or identifier", "The origin of the content cannot be traced.", Confidence.deterministic(),
            "Declare the source identifier.", tags=["advisory"]))
    if "require_verified_origin" in ctx.profile.tags:
        findings.append(make_finding(
            "provenance.origin", "provenance.unverified_origin", "Origin is asserted, not verified", Severity.MEDIUM,
            "AIDAP v1 cannot independently verify the origin of an input", "The profile requires verified origin.",
            Confidence.deterministic(), "Obtain a human attestation through review."))
    if meta.get("derived_from"):
        findings.append(make_finding(
            "provenance.origin", "provenance.derived", "Derived input", Severity.INFO,
            f"Derived from {meta.get('derived_from')} ({meta.get('derivation', 'transformation')})",
            "A transformed derivative is re-validated and inherits no approval.", Confidence.deterministic(),
            "None."))
    return finish(ctx, "provenance.origin", findings, coverage=1.0,
                  metrics={"origin": "asserted", "owner": bool(owner), "source": bool(source)},
                  name="aidap.provenance.metadata")


def check_upstream(ctx: EvalContext) -> CheckResult:
    name = "aidap.provenance.upstream_signals"
    signals = collect_signals(ctx.source_metadata)
    required = bool(ctx.profile.threshold("require_upstream_signals", False))
    if not signals and not required:
        return not_evaluated(ctx, "provenance.upstream", UnknownReason.NOT_APPLICABLE,
                             "No upstream monitoring signals were supplied.", name=name)
    findings = []
    if not signals:
        findings.append(make_finding(
            "provenance.upstream", "provenance.upstream.missing", "No upstream check results supplied", Severity.MEDIUM,
            "The profile requires results from the upstream data-quality tool; none were supplied",
            "AIDAP cannot tell whether the source's own checks ran.", Confidence.deterministic(),
            "Submit the upstream result in the 'upstream_checks' metadata."))
    max_age = timedelta(hours=float(ctx.profile.threshold("upstream_max_age_hours", 72)))
    for s in signals:
        label = f"{s['source']}/{s['name']}"
        if s["status"] == "failed":
            findings.append(make_finding(
                "provenance.upstream", "provenance.upstream.failed", f"Upstream check failed: {label}", Severity.HIGH,
                f"{label} reported 'failed'" + (f" ({s['detail']})" if s.get("detail") else ""),
                "The tool that monitors this source found a problem before the data reached the gate.",
                Confidence.deterministic(), "Resolve the upstream failure, then resubmit.", data={"signal": s}))
        elif s["status"] == "warning":
            findings.append(make_finding(
                "provenance.upstream", "provenance.upstream.warning", f"Upstream check warning: {label}", Severity.LOW,
                f"{label} reported 'warning'", "The upstream tool raised a non-blocking concern.",
                Confidence.deterministic(), "Review the upstream warning.", data={"signal": s}))
        elif s["status"] == "unknown":
            findings.append(make_finding(
                "provenance.upstream", "provenance.upstream.unrecognised", f"Upstream status not understood: {label}",
                Severity.LOW, f"{label} reported a status AIDAP does not recognise",
                "A signal that cannot be read is treated as unknown, not as a pass.", Confidence.deterministic(),
                "Use one of: passed, warning, failed.", data={"signal": s}))
        if s.get("observed_at"):
            try:
                when = datetime.fromisoformat(s["observed_at"])
                if ctx.now - when > max_age:
                    findings.append(make_finding(
                        "provenance.upstream", "provenance.upstream.stale", f"Upstream result is old: {label}",
                        Severity.MEDIUM, f"Observed {s['observed_at'][:16]}; allowed age {max_age}",
                        "An old result says nothing about the current content.", Confidence.deterministic(),
                        "Re-run the upstream check and resubmit.", data={"signal": s}))
            except ValueError:
                pass
    return finish(ctx, "provenance.upstream", findings, coverage=1.0,
                  metrics={"signals": len(signals), "failed": sum(1 for s in signals if s["status"] == "failed"),
                           "asserted": True}, name=name)
