"""What-if evaluation: run a candidate profile/policy against a sample without storing anything or consuming quota.

Only AIDAP's deterministic checks run here - SLAI agents and managed inference are never called by a simulation, so it
cannot cost money or leak sample content to a model. The result says so explicitly.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...assurance_engine import AssuranceEngine, EngineRequest
from ...assurance_engine.ingestion.loader import Limits
from ...domain.accounts.plans import F_CUSTOM_POLICY
from ...domain.data.classification import DataClassification, DestinationClass, SourceClass
from ...domain.evaluations import CHECK_CATALOG, Origin
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import PayloadTooLarge, ValidationFailed
from ..context import Principal

__all__ = ["SimulationService", "MAX_SIMULATION_BYTES"]

MAX_SIMULATION_BYTES = 5_000_000


class SimulationService:
    def __init__(self, deps: Any, plans: Any) -> None:
        self.d, self.plans = deps, plans
        self._engine = AssuranceEngine(external={})

    def simulate(self, p: Principal, *, content: bytes, filename: str = "sample.txt", profile: dict | None = None,
                 profile_id: str = "", policy: dict | None = None, policy_id: str = "", destination: str = "local_index",
                 source_class: str = "unknown", classification: str = "internal", metadata: dict | None = None) -> dict[str, Any]:
        p.require(Permission.POLICIES_READ)
        p.require(Permission.RUNS_SUBMIT)
        if not content:
            raise ValidationFailed("provide a sample to evaluate", details={"fields": {"content": "required"}})
        if len(content) > MAX_SIMULATION_BYTES:
            raise PayloadTooLarge("simulation samples are limited to 5 MB")
        if profile or policy:
            self.plans.require_feature(p.tenant_id, F_CUSTOM_POLICY, "custom profiles and policies")
        if profile:
            prof = self.d.configs._parse("profile", profile, str(profile.get("id") or "draft"))
        elif profile_id:
            prof, _, _ = self.d.configs.resolve(p.tenant_id, "profile", profile_id)
        else:
            raise ValidationFailed("choose a profile or provide a profile document", details={"fields": {"profile_id": "required"}})
        if policy:
            pol = self.d.configs._parse("policy", policy, str(policy.get("id") or "draft"))
        else:
            pol, _, _ = self.d.configs.resolve(p.tenant_id, "policy", policy_id or "standard")
        lint = self.d.configs.lint_documents(profile, policy) if (profile or policy) else {"issues": [], "errors": 0}
        if lint["errors"]:
            raise ValidationFailed("the profile or policy has errors", details={"issues": lint["issues"]})
        withheld = {cid: "simulations run AIDAP's deterministic checks only" for cid, spec in CHECK_CATALOG.items()
                    if spec.origin != Origin.NATIVE}
        req = EngineRequest(
            data=content, profile=prof, policy=pol, filename=filename, destination=DestinationClass.parse(destination),
            classification=DataClassification.parse(classification), source_class=SourceClass.parse(source_class),
            source_metadata=metadata or {}, av=self.d.scanner.scan(content),
            document_reader=getattr(self.d.slai, "documents", None),
            limits=Limits(max_bytes=MAX_SIMULATION_BYTES, max_chars=self.d.settings.max_text_chars,
                          parse_timeout_s=float(self.d.settings.parse_timeout)),
            now=self.d.now(), withheld=withheld, run_id="simulation")
        res = self._engine.evaluate(req, None, None)
        o = res.outcome
        findings = [f.to_dict() for r in res.results.values() for f in r.findings]
        return {"simulation": True, "stored": False, "decision": o.decision.value, "status": o.status.value,
                "summary": o.rationale.summary, "next_action": o.rationale.next_action,
                "reasons": [r.to_dict() for r in o.reasons], "coverage": o.coverage, "findings": findings,
                "checks": [{"check_id": cid, "status": r.status.value, "origin": r.origin.value, "coverage": r.coverage,
                            "findings": len(r.findings), "message": r.message} for cid, r in sorted(res.results.items())],
                "lint": lint, "note": "Nothing was stored and no quota was used. SLAI agents and model-assisted checks are not "
                                      "part of a simulation, so a live run can report additional findings."}
