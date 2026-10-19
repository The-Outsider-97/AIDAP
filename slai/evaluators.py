"""``ExternalEvaluator`` implementations backed by SLAI agents.

Each evaluator: (1) reports availability honestly, (2) builds a bounded envelope, (3) calls the agent through the
governor (timeout + concurrency), (4) maps the output with ``result_mapper``, (5) degrades to an explicit UNKNOWN on
any failure. None of them can lower a decision: they only add findings or gaps.
"""

from __future__ import annotations

from typing import Any

from ..assurance_engine.evaluators.base import EvalContext, finish, unknown
from ..assurance_engine.evaluators.privacy.checks import detect_all
from ..contracts.reasoning import build_reasoning_request, parse_reasoning_response
from ..domain.evaluations import CheckResult, CheckStatus, Confidence, Origin, Severity, UnknownReason
from ..domain.utils.domain_errors import AIDAPError, Unavailable
from .agent_pool import AgentPool
from .governance import AgentGovernor, AgentTimeout
from .job_envelope import build_envelope
from .result_mapper import (map_privacy_identification, map_provenance_report, map_quality_decision,
                            map_safety_assessment)

__all__ = ["SlaiEvaluators", "build_slai_evaluators", "SLAI_EVALUATOR_VERSION"]

SLAI_EVALUATOR_VERSION = "1.0.0"


class _Base:
    check_id = ""
    name = ""
    agent_key = ""
    origin = Origin.SLAI
    sends_content_out = False                    # SLAI agents run in-process, on the operator's own infrastructure
    version = SLAI_EVALUATOR_VERSION

    def __init__(self, pool: AgentPool, gov: AgentGovernor, run_id_of: Any = None, timeout: float = 90.0) -> None:
        self.pool, self.gov, self.timeout = pool, gov, timeout
        self._run_id_of = run_id_of

    def available(self) -> tuple[bool, str]:
        return self.pool.available(self.agent_key)

    def _run_id(self, ctx: EvalContext) -> str:
        return str(ctx.cache.get("run_id") or "run")

    def _guard(self, ctx: EvalContext, fn: Any) -> CheckResult:
        try:
            return fn()
        except AgentTimeout as exc:
            return unknown(ctx, self.check_id, UnknownReason.TIMEOUT, str(exc), name=self.name, version=self.version,
                           origin=self.origin)
        except Unavailable as exc:
            return unknown(ctx, self.check_id, UnknownReason.RUNTIME_UNAVAILABLE, exc.message, name=self.name,
                           version=self.version, origin=self.origin, status=CheckStatus.NOT_EVALUATED)
        except AIDAPError:
            raise
        except Exception as exc:                  # noqa: BLE001 - an agent crash is an UNKNOWN, never a pass
            self.pool.invalidate(self.agent_key, f"{type(exc).__name__}: {str(exc)[:200]}")
            return unknown(ctx, self.check_id, UnknownReason.EVALUATOR_ERROR,
                           f"SLAI {self.agent_key} agent failed: {type(exc).__name__}: {str(exc)[:200]}",
                           name=self.name, version=self.version, origin=self.origin)

    def evaluate(self, ctx: EvalContext) -> CheckResult:
        return self._guard(ctx, lambda: self._evaluate(ctx))

    def _evaluate(self, ctx: EvalContext) -> CheckResult:             # pragma: no cover - abstract
        raise NotImplementedError


class SlaiPrivacy(_Base):
    check_id, name, agent_key = "slai.privacy", "slai.privacy.identification", "privacy_id"

    def _evaluate(self, ctx: EvalContext) -> CheckResult:
        env = build_envelope(ctx, run_id=self._run_id(ctx), check_id=self.check_id)
        agent = self.pool.get(self.agent_key)
        payload = {"units": {u["path"]: u["text"] for u in env.units}}
        with self.pool.lock(self.agent_key):
            raw = self.gov.call(self.agent_key, lambda: agent.identify_entities(payload, stage="aidap",
                                                                                 purpose=env.purpose or None),
                                timeout=self.timeout)
        found, _, _ = detect_all(ctx)
        native_types = {t.value for t, hits in found.items() if hits}
        findings, metrics = map_privacy_identification(raw, native_types)
        metrics["envelope_truncated"] = env.truncated
        return finish(ctx, self.check_id, findings, coverage=env.coverage, metrics=metrics, name=self.name,
                      version=self.version, origin=self.origin)


class SlaiQuality(_Base):
    check_id, name, agent_key = "slai.quality", "slai.quality.agent", "quality"

    def _evaluate(self, ctx: EvalContext) -> CheckResult:
        if not ctx.norm.is_records:
            return unknown(ctx, self.check_id, UnknownReason.NOT_APPLICABLE,
                           "SLAI quality evaluation needs tabular records; this input is free text",
                           name=self.name, version=self.version, origin=self.origin, status=CheckStatus.NOT_EVALUATED)
        env = build_envelope(ctx, run_id=self._run_id(ctx), check_id=self.check_id)
        agent = self.pool.get(self.agent_key)
        rid = self._run_id(ctx)
        with self.pool.lock(self.agent_key):
            decision = self.gov.call(self.agent_key, lambda: agent.evaluate_batch(
                env.records or [], dataset_id=f"aidap-{ctx.profile.id}", source_id=f"aidap-{ctx.source_class.value}",
                batch_id=f"aidap-{rid}", use_case=ctx.profile.task or None, baseline=None,
                source_metadata={k: str(v) for k, v in (ctx.source_metadata or {}).items() if isinstance(v, (str, int, float))},
                context={"origin": "aidap"}), timeout=self.timeout)
        findings, metrics = map_quality_decision(decision if isinstance(decision, dict) else decision.to_dict())
        metrics["envelope_truncated"] = env.truncated
        return finish(ctx, self.check_id, findings, coverage=env.coverage, metrics=metrics, name=self.name,
                      version=self.version, origin=self.origin)


class SlaiSafety(_Base):
    check_id, name, agent_key = "slai.safety", "slai.safety.agent", "safety"

    def _evaluate(self, ctx: EvalContext) -> CheckResult:
        env = build_envelope(ctx, run_id=self._run_id(ctx), check_id=self.check_id)
        agent = self.pool.get(self.agent_key)
        text = env.text()
        with self.pool.lock(self.agent_key):
            out = self.gov.call(self.agent_key, lambda: agent.perform_task(
                text, {"context_type": "data_ingestion", "origin": "aidap", "sanitization_depth": "full"}),
                timeout=self.timeout)
        findings, metrics, cov = map_safety_assessment(out if isinstance(out, dict) else dict(out))
        metrics["envelope_truncated"] = env.truncated
        return finish(ctx, self.check_id, findings, coverage=round(cov * env.coverage, 4), metrics=metrics,
                      name=self.name, version=self.version, origin=self.origin)


class SlaiProvenance(_Base):
    check_id, name, agent_key = "slai.provenance", "slai.provenance.agent", "provenance"

    def _evaluate(self, ctx: EvalContext) -> CheckResult:
        agent = self.pool.get(self.agent_key)
        digest = ctx.norm.original_digest
        aid = f"aidap-input-{digest[-16:]}"
        src = ctx.source_metadata or {}
        with self.pool.lock(self.agent_key):
            def work() -> dict[str, Any]:
                source_id = f"aidap-source-{ctx.source_class.value}"
                agent.register_source(source_id, {"type": ctx.source_class.value, "owner": str(src.get("owner", "")),
                                                  "origin": str(src.get("origin", ""))})
                agent.register_artifact(aid, artifact_type="input", source_id=source_id, digest=digest,
                                        label=ctx.norm.filename or aid,
                                        metadata={k: str(v) for k, v in src.items() if isinstance(v, (str, int, float))})
                return agent.get_reproducibility_report(aid)
            report = self.gov.call(self.agent_key, work, timeout=self.timeout)
        findings, metrics = map_provenance_report(report if isinstance(report, dict) else dict(report))
        return finish(ctx, self.check_id, findings, coverage=1.0, metrics=metrics, name=self.name,
                      version=self.version, origin=self.origin)


class SlaiSemantic(_Base):
    """Model-assisted semantic review through the ReasoningGateway (SLAI's LanguageAgent by default).

    Everything it returns is validated against a strict schema, grounded in the input, and capped at REVIEW by the
    engine (origin ``model``). Content is sent only if the policy allows and the local PII/safety screens were clean.
    """

    check_id, name, agent_key = "slai.semantic", "slai.semantic.reasoner", "language"
    origin = Origin.MODEL

    def __init__(self, pool: AgentPool, gov: AgentGovernor, gateway: Any, timeout: float = 120.0) -> None:
        super().__init__(pool, gov, timeout=timeout)
        self.gateway = gateway
        self.sends_content_out = bool(getattr(gateway, "sends_content_out", False))

    def available(self) -> tuple[bool, str]:
        return self.gateway.available()

    def _evaluate(self, ctx: EvalContext) -> CheckResult:
        env = build_envelope(ctx, run_id=self._run_id(ctx), check_id=self.check_id, redact=True)
        request = build_reasoning_request(check_id=self.check_id, task=ctx.profile.task, purpose=env.purpose,
                                          units=env.units, limits={"semantic_rules": ctx.profile.semantic_rules[:20]})
        payload = self.gov.call(self.agent_key, lambda: self.gateway.reason(request), timeout=self.timeout)
        clean = parse_reasoning_response(payload)
        from ..assurance_engine.evaluators.base import make_finding, pointer
        findings = []
        for f in clean:
            findings.append(make_finding(
                self.check_id, f["code"], f["title"][:200], Severity.parse(f["severity"]), f["observed"][:500],
                f["inference"][:500], Confidence.heuristic(None, "model-assisted; not a calibrated probability"),
                f["recommended_action"][:400],
                pointers=[pointer(s["path"], None, s["start"], s["end"]) for s in f.get("spans", [])[:5]],
                tags=["slai", "model"], origin=Origin.MODEL))
        usage = (payload or {}).get("usage") or {}
        res = finish(ctx, self.check_id, findings, coverage=env.coverage,
                     metrics={"units_sent": len(env.units), "envelope_truncated": env.truncated,
                              "inference_cents": int(usage.get("cents", 0) or 0)},
                     name=self.name, version=self.version, origin=Origin.MODEL)
        return res


class SlaiEvaluators:
    def __init__(self, evaluators: dict[str, Any]) -> None:
        self.by_check = evaluators


def build_slai_evaluators(pool: AgentPool, gov: AgentGovernor, gateway: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "slai.privacy": SlaiPrivacy(pool, gov), "slai.quality": SlaiQuality(pool, gov),
        "slai.safety": SlaiSafety(pool, gov), "slai.provenance": SlaiProvenance(pool, gov),
    }
    if gateway is not None:
        out["slai.semantic"] = SlaiSemantic(pool, gov, gateway)
    return out
