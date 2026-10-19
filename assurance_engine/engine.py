"""AssuranceEngine: the deterministic executor for stages 2-14 of the workflow.

The engine is executable without HTTP, a database, workers or the SLAI runtime.
SLAI agents arrive only as injected ``ExternalEvaluator`` objects, and a stage
store (optional) makes the run resumable: a stage whose output was committed is
replayed from the store, not recomputed, so a restarted worker never repeats
(or re-bills) completed work.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Protocol

from ..domain.evaluations import (CHECK_CATALOG, CheckResult, CheckStatus, Confidence, ConfidenceBasis, Finding,
                                  Origin, Severity, UnknownReason)
from ..domain.evidence import EvaluatorVersion
from ..domain.policies import AssurancePolicy, IntendedUseProfile
from ..domain.utils.domain_helpers import to_jsonable
from .context import EngineRequest
from .decisioning import PlannedCheck, decide
from .evaluators.base import EvalContext, Evaluator, error_result, mandatory_set, run_evaluator, unknown
from .evaluators.external import ExternalEvaluator, withheld_reason
from .evaluators.privacy.checks import detect_all
from .evaluators.registry import NATIVE_EVALUATORS
from .ingestion.provenance import normalize_source_metadata
from .normalization import normalize
from .result import EngineResult
from .validation import ground_findings, validate_findings

__all__ = ["AssuranceEngine", "StageStore", "plan_checks", "stage_of"]

ENGINE_VERSION = "1.0.0"


class StageStore(Protocol):
    def get(self, stage: int) -> dict[str, Any] | None: ...

    def put(self, stage: int, payload: dict[str, Any]) -> str: ...


def stage_of(check_id: str) -> int:
    return CHECK_CATALOG[check_id].stage


def plan_checks(profile: IntendedUseProfile, policy: AssurancePolicy, external_ids: set[str]) -> list[PlannedCheck]:
    mand = mandatory_set(profile, policy)
    wanted: list[str] = [cid for cid, spec in CHECK_CATALOG.items() if spec.default_mandatory]
    for cid in [*profile.required_checks, *profile.optional_checks]:
        if cid in CHECK_CATALOG and cid not in wanted:
            wanted.append(cid)
    if policy.require_baseline and "quality.anomaly" not in wanted:
        wanted.append("quality.anomaly")
    order = {cid: i for i, cid in enumerate(CHECK_CATALOG)}
    planned: list[PlannedCheck] = []
    for cid in sorted(set(wanted), key=lambda c: (stage_of(c), order[c])):
        spec = CHECK_CATALOG[cid]
        enabled, why = True, ""
        if spec.origin != Origin.NATIVE and cid not in external_ids:
            enabled, why = False, "SLAI evaluator is not available in this deployment"
        planned.append(PlannedCheck(cid, cid in mand, enabled, why))
    return planned


class AssuranceEngine:
    def __init__(self, external: dict[str, ExternalEvaluator] | None = None,
                 native: dict[str, Evaluator] | None = None) -> None:
        self.native = dict(native or NATIVE_EVALUATORS)
        self.external = dict(external or {})

    # ------------------------------------------------------------------------------ preparation
    def plan(self, request: EngineRequest) -> list[PlannedCheck]:
        return plan_checks(request.profile, request.policy, set(self.external))

    def prepare(self, request: EngineRequest) -> EvalContext:
        norm = normalize(request.data, filename=request.filename, declared_media_type=request.declared_media_type,
                         limits=request.limits, isolate=request.isolate)
        meta = normalize_source_metadata(request.source_metadata, norm.metadata)
        ctx = EvalContext(norm=norm, profile=request.profile, policy=request.policy, destination=request.destination,
                          classification=request.classification, source_class=request.source_class,
                          source_metadata=meta, baseline=request.baseline, known_revisions=request.known_revisions,
                          now=request.now, av=request.av, mandatory=mandatory_set(request.profile, request.policy),
                          raw=request.data)
        ctx.cache["withheld"] = dict(request.withheld)
        ctx.cache["run_id"] = request.run_id
        return ctx

    # ------------------------------------------------------------------------------ one stage
    def run_stage(self, ctx: EvalContext, stage: int, planned: list[PlannedCheck]) -> list[CheckResult]:
        out: list[CheckResult] = []
        for pc in planned:
            if stage_of(pc.check_id) != stage:
                continue
            res = self._run_check(ctx, pc)
            ctx.memo[pc.check_id] = res
            out.append(res)
        return out

    def _run_check(self, ctx: EvalContext, pc: PlannedCheck) -> CheckResult:
        cid = pc.check_id
        if cid in ctx.memo:                       # computed early by the preliminary local screen
            return ctx.memo[cid]
        spec = CHECK_CATALOG[cid]
        if spec.origin == Origin.NATIVE:
            ev = self.native.get(cid)
            if ev is None:
                return error_result(ctx, cid, UnknownReason.NOT_CONFIGURED, "no evaluator is registered")
            return self._validated(run_evaluator(ev, ctx), ctx)
        held = ctx.cache.get("withheld", {}).get(cid)
        if held:
            return unknown(ctx, cid, UnknownReason.PLAN, held, status=CheckStatus.NOT_EVALUATED, origin=spec.origin)
        ext = self.external.get(cid)
        if ext is None:
            return unknown(ctx, cid, UnknownReason.RUNTIME_UNAVAILABLE, pc.skip_reason or "SLAI evaluator unavailable",
                           status=CheckStatus.NOT_EVALUATED, origin=spec.origin)
        ok, why = ext.available()
        if not ok:
            return unknown(ctx, cid, UnknownReason.RUNTIME_UNAVAILABLE, why or "SLAI runtime unavailable",
                           status=CheckStatus.NOT_EVALUATED, name=ext.name, version=ext.version, origin=ext.origin)
        if spec.external or spec.origin == Origin.MODEL:
            self._preliminary_screen(ctx)        # local privacy + security screening precedes external evaluation
            reason = withheld_reason(ctx, ext)
            if reason is None:
                inj = ctx.memo.get("safety.injection")
                if inj and any(f.severity >= Severity.HIGH for f in inj.findings):
                    reason = "the local safety screen flagged this input; it is not sent for model-assisted evaluation"
            if reason:
                return unknown(ctx, cid, UnknownReason.WITHHELD_PRIVACY if "privacy" in reason or "sensitive" in reason
                               else UnknownReason.PLAN, reason, status=CheckStatus.NOT_EVALUATED, name=ext.name,
                               version=ext.version, origin=ext.origin)
        wrapped = Evaluator(cid, ext.name, ext.evaluate, ext.version, ext.origin)
        res = run_evaluator(wrapped, ctx)
        if res.findings:
            res.findings, dropped = ground_findings(res.findings, ctx.norm)
            if dropped:
                res.metrics["ungrounded_findings_discarded"] = dropped
                if res.status == CheckStatus.FAILED and not any(f.severity > Severity.INFO for f in res.findings):
                    res.status = CheckStatus.PASSED      # nothing grounded remains; the model's claims are discarded
        return self._validated(res, ctx)

    def _validated(self, res: CheckResult, ctx: EvalContext) -> CheckResult:
        problems = validate_findings(res)
        if problems:
            return error_result(ctx, res.check_id, UnknownReason.MALFORMED_RESULT,
                                "evaluator returned incomplete findings: " + "; ".join(problems[:3]),
                                name=res.evaluator, version=res.evaluator_version, origin=res.origin)
        return res

    def _preliminary_screen(self, ctx: EvalContext) -> None:
        detect_all(ctx)
        if "safety.injection" not in ctx.memo:
            ev = self.native["safety.injection"]
            ctx.memo["safety.injection"] = run_evaluator(ev, ctx)

    # ------------------------------------------------------------------------------ whole run
    def evaluate(self, request: EngineRequest, store: StageStore | None = None,
                 on_stage: Callable[[int, str, dict[str, Any]], None] | None = None) -> EngineResult:
        planned = self.plan(request)
        ctx = self.prepare(request)
        log: list[dict[str, Any]] = []
        results: dict[str, CheckResult] = {}

        def note(stage: int, state: str, extra: dict[str, Any]) -> None:
            entry = {"stage": stage, "state": state, **extra}
            log.append(entry)
            if on_stage:
                on_stage(stage, state, extra)

        for stage in range(3, 13):
            if not any(stage_of(p.check_id) == stage for p in planned):
                continue
            cached = store.get(stage) if store else None
            if cached is not None:
                for d in cached.get("results", []):
                    r = CheckResult.from_dict(d)
                    results[r.check_id] = r
                    ctx.memo[r.check_id] = r
                note(stage, "replayed", {"checks": len(cached.get("results", []))})
                continue
            started = time.monotonic()
            stage_results = self.run_stage(ctx, stage, planned)
            for r in stage_results:
                results[r.check_id] = r
            payload = {"results": [r.to_dict() for r in stage_results]}
            ref = store.put(stage, payload) if store else ""
            note(stage, "committed", {"checks": len(stage_results), "ms": int((time.monotonic() - started) * 1000),
                                      "checkpoint": ref})
        # checks that were planned but never produced a result (e.g. disabled) stay absent -> unresolved
        for pc in planned:
            if not pc.enabled and pc.check_id not in results:
                results[pc.check_id] = unknown(ctx, pc.check_id, UnknownReason.RUNTIME_UNAVAILABLE, pc.skip_reason,
                                               status=CheckStatus.NOT_EVALUATED, origin=CHECK_CATALOG[pc.check_id].origin)
        confidence = self._confidence_stage(results)
        note(13, "committed", {"basis": confidence})
        outcome = decide(results=results, planned=planned, policy=request.policy, profile=request.profile,
                         destination=request.destination, classification=request.classification,
                         source_class=request.source_class.value, grants=request.grants, now=request.now)
        note(14, "committed", {"decision": outcome.decision.value})
        evaluators = sorted({(r.check_id, r.evaluator, r.evaluator_version, r.origin.value) for r in results.values()})
        evs = [EvaluatorVersion(c, n or c, v or ENGINE_VERSION, o) for c, n, v, o in evaluators]
        return EngineResult(ctx.norm.to_summary(), planned, results, outcome, evs, log, confidence,
                            to_jsonable(ctx.source_metadata), ctx.cache.get("column_stats"))

    @staticmethod
    def _confidence_stage(results: dict[str, CheckResult]) -> dict[str, Any]:
        """Stage 13: record confidence honestly. Nothing is 'calibrated'; unknowns are explicit."""
        counts = {b.value: 0 for b in ConfidenceBasis}
        for r in results.values():
            for f in r.findings:
                counts[f.confidence.basis.value] += 1
        unknown_checks = [r.check_id for r in results.values() if not r.status.conclusive]
        return {"by_basis": counts, "unknown_checks": unknown_checks, "calibrated": False,
                "note": "Heuristic values are relative scores, not calibrated probabilities."}
