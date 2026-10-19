"""Evaluator base: the context every check receives and helpers that build typed results.

Evaluators are pure functions of an ``EvalContext``. They return findings
only; they never change policy, authorisation or delivery (whitepaper 7.4.3).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

from ...domain.data.classification import DataClassification, DestinationClass, SourceClass
from ...domain.evaluations import (CHECK_CATALOG, Category, CheckResult, CheckStatus, Confidence, EvidencePointer,
                                   Finding, Origin, Severity, UnknownReason)
from ...domain.policies.models import AssurancePolicy, IntendedUseProfile
from ..normalization.models import NormalizedInput
from .privacy.redact import safe_excerpt  # noqa: E402

__all__ = ["EvalContext", "Evaluator", "EVALUATOR_VERSION", "make_finding", "finish", "unknown",
           "not_evaluated", "error_result", "run_evaluator", "pointer", "mandatory_set"]

EVALUATOR_VERSION = "1.0.0"


def mandatory_set(profile: IntendedUseProfile, policy: AssurancePolicy) -> set[str]:
    ids = set(profile.required_checks)
    for cid, spec in CHECK_CATALOG.items():
        if spec.default_mandatory and policy.mandatory_overrides.get(cid, True):
            ids.add(cid)
    for cid, flag in policy.mandatory_overrides.items():
        if flag and cid in CHECK_CATALOG:
            ids.add(cid)
    if policy.require_av_scan:
        ids.add("safety.file")
    if policy.require_baseline:
        ids.add("quality.anomaly")
    return ids


@dataclass
class EvalContext:
    norm: NormalizedInput
    profile: IntendedUseProfile
    policy: AssurancePolicy
    destination: DestinationClass = DestinationClass.LOCAL_INDEX
    classification: DataClassification = DataClassification.INTERNAL
    source_class: SourceClass = SourceClass.UNKNOWN
    source_metadata: dict[str, Any] = field(default_factory=dict)   # submitter-declared + embedded
    baseline: dict[str, Any] | None = None                          # *approved* baseline document only
    known_revisions: list[dict[str, Any]] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime.now().astimezone())
    av: dict[str, Any] | None = None                                # malware-scan verdict
    mandatory: set[str] = field(default_factory=set)
    memo: dict[str, CheckResult] = field(default_factory=dict)      # completed checks, by id
    cache: dict[str, Any] = field(default_factory=dict)            # evaluator-private derived data
    raw: bytes = b""

    def is_mandatory(self, check_id: str) -> bool:
        return check_id in self.mandatory


@dataclass(frozen=True)
class Evaluator:
    check_id: str
    name: str
    fn: Callable[[EvalContext], CheckResult]
    version: str = EVALUATOR_VERSION
    origin: Origin = Origin.NATIVE


def pointer(path: str, text: str | None = None, start: int | None = None, end: int | None = None, *,
            hide: bool = False) -> EvidencePointer:
    excerpt, digest = "", ""
    if text is not None and start is not None and end is not None:
        excerpt = safe_excerpt(text, start, end, hide_span=hide)
        digest = "sha256:" + hashlib.sha256(text[start:end].encode("utf-8", "replace")).hexdigest()[:24]
    return EvidencePointer(path, start, end, excerpt, digest)


def make_finding(check_id: str, code: str, title: str, severity: Severity, observed: str, inference: str,
                 confidence: Confidence, action: str, *, pointers: Iterable[EvidencePointer] = (), count: int = 1,
                 tags: Iterable[str] = (), data: dict[str, Any] | None = None, origin: Origin = Origin.NATIVE,
                 mandatory: bool = False) -> Finding:
    spec = CHECK_CATALOG[check_id]
    ptrs = list(pointers)[:8]
    key = f"{check_id}|{code}|{'|'.join(p.path for p in ptrs[:3])}|{observed[:80]}"
    fid = "f_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:14]
    return Finding(fid, check_id, spec.category, code, title, severity, observed, inference, confidence, action,
                   origin, ptrs, count, mandatory, list(tags), data or {})


def finish(ctx: EvalContext, check_id: str, findings: list[Finding], *, coverage: float | None = 1.0,
           metrics: dict[str, Any] | None = None, message: str = "", name: str = "",
           version: str = EVALUATOR_VERSION, origin: Origin = Origin.NATIVE) -> CheckResult:
    mand = ctx.is_mandatory(check_id)
    for f in findings:
        f.mandatory = f.mandatory or mand
    failed = any(f.severity > Severity.INFO for f in findings)
    return CheckResult(check_id, CheckStatus.FAILED if failed else CheckStatus.PASSED, findings,
                       name or check_id, version, origin, mand, coverage, None, message, 0, metrics or {})


def unknown(ctx: EvalContext, check_id: str, reason: UnknownReason, message: str, *, name: str = "",
            version: str = EVALUATOR_VERSION, origin: Origin = Origin.NATIVE,
            status: CheckStatus = CheckStatus.UNKNOWN) -> CheckResult:
    return CheckResult(check_id, status, [], name or check_id, version, origin, ctx.is_mandatory(check_id), None,
                       reason, message)


def not_evaluated(ctx: EvalContext, check_id: str, reason: UnknownReason, message: str, **kw: Any) -> CheckResult:
    return unknown(ctx, check_id, reason, message, status=CheckStatus.NOT_EVALUATED, **kw)


def error_result(ctx: EvalContext, check_id: str, reason: UnknownReason, message: str, *, name: str = "",
                 version: str = EVALUATOR_VERSION, origin: Origin = Origin.NATIVE) -> CheckResult:
    return unknown(ctx, check_id, reason, message, status=CheckStatus.ERROR, name=name, version=version,
                   origin=origin)


def run_evaluator(ev: Evaluator, ctx: EvalContext) -> CheckResult:
    """Run one evaluator. An exception or malformed result is ERROR, never a silent pass."""
    started = time.monotonic()
    try:
        result = ev.fn(ctx)
    except Exception as exc:  # fail closed: the detector may not have run
        result = error_result(ctx, ev.check_id, UnknownReason.EVALUATOR_ERROR,
                              f"{ev.name} raised {exc.__class__.__name__}", name=ev.name, version=ev.version,
                              origin=ev.origin)
    if not isinstance(result, CheckResult) or result.check_id != ev.check_id:
        result = error_result(ctx, ev.check_id, UnknownReason.MALFORMED_RESULT,
                              f"{ev.name} returned a malformed result", name=ev.name, version=ev.version,
                              origin=ev.origin)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    result.mandatory = ctx.is_mandatory(ev.check_id)
    if not result.evaluator:
        result.evaluator, result.evaluator_version = ev.name, ev.version
    return result
