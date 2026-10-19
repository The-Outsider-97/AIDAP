"""Authoritative AIDAP decision engine (stage 14).

Ordered rules (first the hard rules, then policy rules, then completeness):

* H1–H5  hard rules no policy can remove (prohibited destination, secrets, malware, integrity, tool directives)
* R1     per-finding policy effect (explicit policy rules, else severity mapping; model-origin capped at REVIEW)
* R2     unresolved mandatory check (unknown / not evaluated / error / missing) -> never PASS
* R3     mandatory check coverage below the policy minimum -> REVIEW
* R4     active, attributable exceptions waive covered, waivable reasons
* R5     shadow-mode policies compute a decision but never authorise release

Decision = worst-of the remaining reasons. Optional-check gaps stay visible in coverage;
they are never described as successful validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ...domain.data.classification import DataClassification, DestinationClass
from ...domain.decisions import (ArtifactDisposition, Decision, DecisionRationale, DecisionStatus, ExceptionGrant,
                                 RationaleStep, Reason, combine, guidance)
from ...domain.evaluations import CheckResult, CheckStatus, Finding, Severity
from ...domain.policies import AssurancePolicy, IntendedUseProfile, MatchContext, resolve_effect
from .policy import match_hard_rule
from .resolver import apply_exceptions
from .thresholds import ordering_score

__all__ = ["PlannedCheck", "DecisionOutcome", "decide", "coverage_summary"]


@dataclass
class PlannedCheck:
    check_id: str
    mandatory: bool
    enabled: bool = True
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "mandatory": self.mandatory, "enabled": self.enabled,
                "skip_reason": self.skip_reason}


@dataclass
class DecisionOutcome:
    decision: Decision
    status: DecisionStatus
    disposition: ArtifactDisposition
    reasons: list[Reason]
    rationale: DecisionRationale
    coverage: dict[str, Any]
    score: float
    shadow: bool
    expires_at: datetime | None
    exception_ids: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def coverage_summary(planned: list[PlannedCheck], results: dict[str, CheckResult], min_cov: float) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    mand_total = mand_ok = 0
    unresolved: list[str] = []
    optional_unresolved: list[str] = []
    min_mand_cov = 1.0
    for pc in planned:
        res = results.get(pc.check_id)
        if res is None:
            status, cov, reason = "not_evaluated", None, pc.skip_reason or "not run"
        else:
            status, cov = res.status.value, res.coverage
            reason = res.unknown_reason.value if res.unknown_reason else ""
        conclusive = res is not None and res.status.conclusive
        checks[pc.check_id] = {"status": status, "mandatory": pc.mandatory, "coverage": cov, "reason": reason,
                               "evaluator": res.evaluator if res else "", "origin": res.origin.value if res else "",
                               "message": (res.message if res else pc.skip_reason)}
        if pc.mandatory:
            mand_total += 1
            if conclusive:
                mand_ok += 1
                if cov is not None:
                    min_mand_cov = min(min_mand_cov, cov)
            else:
                unresolved.append(pc.check_id)
        elif not conclusive:
            optional_unresolved.append(pc.check_id)
    return {"checks": checks, "mandatory_total": mand_total, "mandatory_conclusive": mand_ok,
            "unresolved_mandatory": unresolved, "unresolved_optional": optional_unresolved,
            "min_mandatory_coverage": round(min_mand_cov, 4), "min_coverage_required": min_cov,
            "complete": not unresolved and min_mand_cov >= min_cov}


def decide(*, results: dict[str, CheckResult], planned: list[PlannedCheck], policy: AssurancePolicy,
           profile: IntendedUseProfile, destination: DestinationClass, classification: DataClassification,
           source_class: str, grants: list[ExceptionGrant], now: datetime) -> DecisionOutcome:
    ctx = MatchContext(destination, classification, profile.id, source_class)
    reasons: list[Reason] = []
    steps: list[RationaleStep] = []
    all_findings = [f for r in results.values() for f in r.findings]
    quarantine_artifact = False

    # H1-H5: hard rules
    for hr_id in ("H1", "H2", "H3", "H4", "H5"):
        fired: list[Reason] = []
        for f in all_findings:
            hr = match_hard_rule(f.code)
            if hr and hr.id == hr_id:
                quarantine_artifact = quarantine_artifact or hr.quarantine_artifact
                fired.append(Reason(f.code, f.title, hr.effect, f.severity, f.check_id, [f.id], hr_id,
                                    False, guidance(f.code)))
        reasons += fired
        steps.append(RationaleStep(hr_id, _HARD_DESC[hr_id],
                                   combine([r.effect for r in fired]) if fired else Decision.PASS,
                                   sorted({r.code for r in fired})))

    # R1: per-finding effect
    fired = []
    noted = 0
    hard_ids = {fid for r in reasons for fid in r.finding_ids}
    for f in all_findings:
        if f.id in hard_ids or f.severity == Severity.INFO:
            continue
        effect, rule_id = resolve_effect(policy, f, ctx)
        if effect == Decision.PASS:
            noted += 1
            continue
        fired.append(Reason(f.code, f.title, effect, f.severity, f.check_id, [f.id], rule_id, True, guidance(f.code)))
    reasons += _merge(fired)
    steps.append(RationaleStep("R1", f"Policy effect of {len(all_findings)} finding(s) "
                                     f"({noted} noted without consequence)",
                               combine([r.effect for r in fired]) if fired else Decision.PASS,
                               sorted({r.code for r in fired})))

    # R2: unresolved mandatory
    fired = []
    unresolved_effect = Decision.parse(policy.unknown_mandatory_effect, Decision.REVIEW)
    if unresolved_effect == Decision.PASS:
        unresolved_effect = Decision.REVIEW
    for pc in planned:
        if not pc.mandatory:
            continue
        res = results.get(pc.check_id)
        if res is None or not res.status.conclusive:
            why = (res.message if res and res.message else pc.skip_reason) or "the check did not complete"
            fired.append(Reason(f"incomplete.{pc.check_id}", f"Mandatory check '{pc.check_id}' is unresolved: {why}",
                                unresolved_effect, Severity.HIGH, pc.check_id, [], "R2", True,
                                guidance("incomplete.")))
    reasons += fired
    steps.append(RationaleStep("R2", "Mandatory checks must finish; unknown is never pass",
                               combine([r.effect for r in fired]) if fired else Decision.PASS,
                               sorted({r.code for r in fired})))

    # R3: coverage
    fired = []
    for pc in planned:
        res = results.get(pc.check_id)
        if pc.mandatory and res is not None and res.status.conclusive and res.coverage is not None \
                and res.coverage < policy.min_coverage:
            fired.append(Reason(f"incomplete.coverage.{pc.check_id}",
                                f"'{pc.check_id}' examined {res.coverage:.0%} of the input; the policy requires "
                                f"{policy.min_coverage:.0%}", Decision.REVIEW, Severity.MEDIUM, pc.check_id, [], "R3",
                                True, guidance("incomplete.")))
    reasons += fired
    steps.append(RationaleStep("R3", f"Mandatory coverage at least {policy.min_coverage:.0%}",
                               combine([r.effect for r in fired]) if fired else Decision.PASS,
                               sorted({r.code for r in fired})))

    # R4: exceptions
    reasons, used = apply_exceptions(reasons, grants, policy, now)
    waived = [r for r in reasons if r.waived_by]
    steps.append(RationaleStep("R4", f"{len(waived)} reason(s) covered by active attributable exceptions",
                               Decision.PASS if waived else Decision.PASS, sorted({r.code for r in waived})))

    standing = [r for r in reasons if not r.waived_by]
    decision = combine([r.effect for r in standing])
    shadow = policy.mode == "shadow"
    steps.append(RationaleStep("R5", "Shadow policies compute a decision but never authorise release"
                                    if shadow else "Enforcing policy", decision, []))

    cov = coverage_summary(planned, results, policy.min_coverage)
    # a PASS must have every mandatory check conclusive (belt and braces: R2 already guarantees it)
    if decision == Decision.PASS and (cov["unresolved_mandatory"]):
        decision = Decision.REVIEW
    if decision == Decision.PASS and cov["unresolved_optional"]:
        steps.append(RationaleStep("note", "Optional checks unresolved; they are listed in coverage and are not "
                                           "claimed as successful validation", Decision.PASS,
                                   [f"optional:{c}" for c in cov["unresolved_optional"]]))
    if decision == Decision.QUARANTINE or (decision == Decision.BLOCK and quarantine_artifact):
        disposition = ArtifactDisposition.QUARANTINED
    else:
        disposition = ArtifactDisposition.RETAINED
    top = max(standing, key=lambda r: (r.effect.rank, r.severity.rank), default=None)
    summary = _summary(decision, standing, waived, cov)
    next_action = (top.guidance if top else
                   ("Release the approved artifact to the destination." if decision == Decision.PASS else ""))
    return DecisionOutcome(
        decision=decision, status=DecisionStatus.SHADOW if shadow else DecisionStatus.ACTIVE,
        disposition=disposition, reasons=reasons, rationale=DecisionRationale(summary, steps, next_action),
        coverage=cov, score=ordering_score(all_findings), shadow=shadow,
        expires_at=now + timedelta(hours=policy.decision_valid_hours), exception_ids=used, findings=all_findings)


_HARD_DESC = {
    "H1": "Prohibited destination blocks the requested operation",
    "H2": "Credentials are never released",
    "H3": "Malicious artifacts are isolated",
    "H4": "Integrity mismatch isolates the artifact",
    "H5": "Embedded tool or exfiltration directives isolate the artifact",
}


def _merge(reasons: list[Reason]) -> list[Reason]:
    """One reason per (code, effect); finding ids are combined."""
    out: dict[tuple[str, Decision], Reason] = {}
    for r in reasons:
        key = (r.code, r.effect)
        if key in out:
            out[key].finding_ids += r.finding_ids
            out[key].severity = max(out[key].severity, r.severity)
        else:
            out[key] = r
    return list(out.values())


def _summary(decision: Decision, standing: list[Reason], waived: list[Reason], cov: dict[str, Any]) -> str:
    if decision == Decision.PASS:
        base = (f"All {cov['mandatory_total']} mandatory checks completed with acceptable results"
                if cov["mandatory_total"] else "No mandatory checks were configured")
        if waived:
            base += f"; {len(waived)} finding(s) are covered by attributable exceptions"
        if cov["unresolved_optional"]:
            base += f"; {len(cov['unresolved_optional'])} optional check(s) did not complete"
        return base + "."
    codes = ", ".join(sorted({r.code for r in standing})[:4])
    word = {"review": "held for review", "quarantine": "quarantined", "block": "blocked"}[decision.value]
    return f"Input {word}: {codes}" + ("…" if len({r.code for r in standing}) > 4 else "") + "."
