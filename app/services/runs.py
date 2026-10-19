"""The assurance run: submission, the 20-stage pipeline, re-decision, redaction, release.

Stages 1-2 happen at submission/normalisation, 3-14 inside the deterministic engine (stage outputs checkpointed through
SLAI's CheckpointManager), and 15-20 here: disposition, evidence, audit, checkpointing, alerting, delivery.
"""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from typing import Any

from ...assurance_engine import AssuranceEngine, EngineRequest
from ...assurance_engine.decisioning import PlannedCheck, decide
from ...assurance_engine.evaluators.privacy.redact import redact_bytes
from ...assurance_engine.ingestion.loader import Limits
from ...contracts.versions import DECISION_SCHEMA
from ...domain.accounts.usage import METER_CPU_MS, METER_INFERENCE_CENTS, METER_RUN, METER_SCAN_BYTES, billable_bytes
from ...domain.data.classification import DataClassification, DeliveryKind, DestinationClass, SourceClass
from ...domain.decisions import (ArtifactDisposition, Decision, DecisionStatus, ExceptionGrant, FitnessDecision)
from ...domain.evaluations import CheckResult
from ...domain.evidence import EvidenceBundle, build_provenance, verify_bundle
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import (AIDAPError, Conflict, Forbidden, IntegrityViolation, NotFound, PayloadTooLarge,
                                           ValidationFailed)
from ...domain.utils.domain_helpers import add_days, iso, new_id, parse_iso, sha256_hex, to_jsonable
from ...domain.workflows.jobs import TERMINAL_JOB_STATES, JobState
from ...version import SLAI_BASELINE_COMMIT, __version__
from ..context import Principal
from ..utils.common import audit, audit_system, clean_page, get_or_404
from .plans import PlanService, UsageService
from .run_queries import RunQueries
from .workspace import AlertService, BaselineService

__all__ = ["RunService", "STAGE_NAMES"]

STAGE_NAMES = {1: "ingestion", 2: "normalization", 3: "format_validation", 4: "structural_quality", 5: "statistical_quality",
               6: "anomaly_detection", 7: "relationship_analysis", 8: "semantic_fitness", 9: "privacy_screening",
               10: "safety_screening", 11: "provenance_evidence", 12: "intended_use_fitness", 13: "confidence",
               14: "policy_decision", 15: "disposition", 16: "evidence_generation", 17: "audit_logging",
               18: "checkpointing", 19: "alerting", 20: "delivery"}
_MAX_REVISIONS = 50


class RunService(RunQueries):
    def __init__(self, deps: Any, plans: PlanService, usage: UsageService, baselines: BaselineService,
                 alerts: AlertService, notify: Any, delivery: Any) -> None:
        self.d, self.plans, self.usage, self.baselines, self.alerts = deps, plans, usage, baselines, alerts
        self.notify, self.delivery = notify, delivery
        self._engine_cache: AssuranceEngine | None = None

    # ================================================================== submission (stage 1)
    def submit(self, p: Principal, *, project_id: str, data: bytes, filename: str = "", media_type: str = "",
               profile_id: str = "", policy_id: str = "", destination_id: str = "", source_class: str = "unknown",
               classification: str = "internal", label: str = "", idempotency_key: str = "", asset_name: str = "",
               metadata: dict[str, Any] | None = None, source: str = "api", parent_run_id: str | None = None,
               derived_from: str | None = None, derivation: str = "", version_label: str = "") -> dict[str, Any]:
        p.require(Permission.RUNS_SUBMIT)
        p.require_project(project_id)
        project = get_or_404(self.d, "projects", project_id, p.tenant_id, "project")
        if project.get("archived"):
            raise Conflict("this project is archived", code="project_archived")
        if not data:
            raise ValidationFailed("the input is empty", details={"fields": {"file": "empty"}})
        if len(data) > self.d.settings.max_upload_bytes:
            raise PayloadTooLarge("the input exceeds the platform limit")
        profile_id = profile_id or project.get("default_profile_id") or ""
        if not profile_id:
            raise ValidationFailed("choose an intended-use profile (the project has no default)",
                                   details={"fields": {"profile_id": "required"}})
        policy_id = policy_id or project.get("default_policy_id") or "standard"
        destination_id = destination_id or project.get("default_destination_id") or ""
        profile, pv, _ = self.d.configs.resolve(p.tenant_id, "profile", profile_id)
        policy, qv, _ = self.d.configs.resolve(p.tenant_id, "policy", policy_id)
        dest = None
        if destination_id:
            dest = get_or_404(self.d, "destinations", destination_id, p.tenant_id, "destination")
            if not dest.get("enabled", True):
                raise Conflict("this destination is disabled", code="destination_disabled")
        digest = sha256_hex(data)
        idem_key = f"{p.tenant_id}:idem:{idempotency_key}" if idempotency_key else None
        if idem_key:
            prior = self.d.db.get_by_ukey("runs", idem_key)
            if prior:
                if prior.get("input_digest") != "sha256:" + digest and prior.get("input_digest") != digest:
                    raise Conflict("this idempotency key was already used with different content", code="idempotency_conflict")
                return {**prior, "idempotent_replay": True}
        admission = self.usage.admit(p.tenant_id, len(data))
        now = self.d.now()
        asset_name = asset_name or filename or "untitled"
        with self.d.db.transaction():
            asset = self.d.db.get_by_ukey("assets", f"{p.tenant_id}:{project_id}:{asset_name}")
            if asset is None:
                asset = {"id": new_id("ast"), "tenant_id": p.tenant_id, "project_id": project_id, "name": asset_name,
                         "created_at": iso(now), "source_class": source_class, "classification": classification,
                         "metadata": {}}
                self.d.db.insert("assets", asset, tenant_id=p.tenant_id, ukey=f"{p.tenant_id}:{project_id}:{asset_name}")
            vno = 1 + self.d.db.count("versions", tenant_id=p.tenant_id, where={"asset_id": asset["id"]})
            vid = new_id("ver")
            blob_ref = self.d.blobs.put(f"{p.tenant_id}/in/{vid}", data)
            version = {"id": vid, "tenant_id": p.tenant_id, "project_id": project_id, "asset_id": asset["id"],
                       "version_no": vno, "content_digest": "sha256:" + digest, "size": len(data), "blob_ref": blob_ref,
                       "created_at": iso(now), "created_by": p.actor, "filename": filename, "media_type": media_type,
                       "source_metadata": metadata or {}, "derived_from": derived_from, "derivation": derivation,
                       "purged": False, "source_class": source_class, "classification": classification}
            self.d.db.insert("versions", version, tenant_id=p.tenant_id)
            rid = new_id("run")
            run = {"id": rid, "tenant_id": p.tenant_id, "project_id": project_id, "asset_id": asset["id"],
                   "version_id": vid, "profile_id": profile_id, "profile_version": pv, "policy_id": policy_id,
                   "policy_version": qv, "destination_id": destination_id or None, "state": JobState.QUEUED.value,
                   "created_by": p.actor, "created_at": iso(now), "idempotency_key": idempotency_key or "",
                   "input_digest": "sha256:" + digest, "baseline_id": None, "decision_id": None, "decision": None,
                   "attempts": 0, "error": "", "finished_at": None, "parent_run_id": parent_run_id, "source": source,
                   "label": label, "filename": filename, "size": len(data), "asset_name": asset_name,
                   "version_no": vno, "warnings": admission["warnings"], "source_class": source_class,
                   "classification": classification, "plan_id": admission["plan"]}
            if not self.d.db.insert("runs", run, tenant_id=p.tenant_id, ukey=idem_key):
                raise Conflict("this idempotency key is already in use", code="idempotency_conflict")
            self._stage(rid, 1, "committed", message="input accepted", metrics={"bytes": len(data), "digest": "sha256:" + digest})
        audit(self.d, p, "run.submitted", rid, {"project": project_id, "profile": f"{profile_id}@{pv}",
                                                 "policy": f"{policy_id}@{qv}", "bytes": len(data), "source": source})
        self.d.queue.enqueue("run", {"run_id": rid, "tenant_id": p.tenant_id}, dedupe_key=f"run:{rid}",
                             max_attempts=self.d.settings.max_attempts)
        return run

    def _stage(self, run_id: str, stage: int, state: str, *, message: str = "", checkpoint: str | None = None,
               metrics: dict[str, Any] | None = None, attempt: int = 1, started: str | None = None) -> None:
        run = self.d.db.get("runs", run_id) or {}
        now = iso(self.d.now())
        self.d.db.put("run_stages", {"id": f"{run_id}:{stage}", "run_id": run_id, "stage": stage, "name": STAGE_NAMES[stage],
                                     "state": state, "attempt": attempt, "started_at": started or now, "finished_at": now,
                                     "checkpoint": checkpoint, "message": message, "metrics": metrics or {},
                                     "created_at": now}, tenant_id=run.get("tenant_id", ""))

    # ================================================================== execution (worker)
    def engine(self) -> AssuranceEngine:
        if self._engine_cache is None:
            external = self.d.slai.evaluators() if self.d.slai is not None else {}
            self._engine_cache = AssuranceEngine(external=external)
        return self._engine_cache

    def execute(self, run_id: str) -> str:
        """Run the pipeline. Returns the final job state. Unexpected errors propagate so the queue can retry; after the
        last attempt the run is FAILED - and a failed run is never PASS."""
        run = self.d.db.get("runs", run_id)
        if run is None:
            return "missing"
        if JobState(run["state"]) in TERMINAL_JOB_STATES:
            return run["state"]
        run["state"] = JobState.RUNNING.value
        run["attempts"] = int(run.get("attempts", 0)) + 1
        self.d.db.put("runs", run, tenant_id=run["tenant_id"])
        try:
            self._execute(run)
        except IntegrityViolation as exc:                              # deterministic: retrying cannot help
            self._fail(run, exc.message)
            return JobState.FAILED.value
        except Exception as exc:                                       # noqa: BLE001
            permanent = isinstance(exc, AIDAPError) and exc.http_status < 500
            if permanent or run["attempts"] >= self.d.settings.max_attempts:
                self._fail(run, getattr(exc, "message", None) or f"{type(exc).__name__}: {str(exc)[:300]}")
                return JobState.FAILED.value
            run["state"] = JobState.QUEUED.value
            run["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            self.d.db.put("runs", run, tenant_id=run["tenant_id"])
            raise
        return JobState.COMPLETED.value

    def _fail(self, run: dict[str, Any], message: str) -> None:
        run["state"], run["error"], run["finished_at"] = JobState.FAILED.value, message[:500], iso(self.d.now())
        self.d.db.put("runs", run, tenant_id=run["tenant_id"])
        audit_system(self.d, run["tenant_id"], "run.failed", run["id"], {"error": message[:300]})
        self.alerts.raise_alert(run["tenant_id"], run["project_id"], "run_failed", f"failed:{run['project_id']}",
                                "A run could not be completed",
                                f"Run {run['id']} failed: {message[:300]}. No decision was issued, so nothing was released.",
                                "high", run["id"])

    def _known_revisions(self, run: dict[str, Any], version: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for v in self.d.db.find("versions", tenant_id=run["tenant_id"], where={"asset_id": version["asset_id"]},
                                order_by="version_no", desc=False, limit=_MAX_REVISIONS):
            if v["id"] == version["id"]:
                continue
            rev = (v.get("source_metadata") or {}).get("source_revision")
            if rev in (None, ""):
                continue
            prior = self.d.db.find("runs", tenant_id=run["tenant_id"], where={"version_id": v["id"], "state": "completed"},
                                   limit=1)
            if prior and prior[0].get("decision") == "pass":            # only approved revisions can supersede
                out.append({"revision": str(rev), "digest": v["content_digest"].replace("sha256:", ""), "version_id": v["id"]})
        return out

    def _execute(self, run: dict[str, Any]) -> None:
        t0 = time.monotonic()
        tenant, rid = run["tenant_id"], run["id"]
        plan = self.plans.plan_for(tenant)
        profile, _, profile_doc = self.d.configs.resolve(tenant, "profile", run["profile_id"], run["profile_version"])
        policy, _, policy_doc = self.d.configs.resolve(tenant, "policy", run["policy_id"], run["policy_version"])
        version = get_or_404(self.d, "versions", run["version_id"], tenant, "input")
        data = self.d.blobs.get(version["blob_ref"])
        if "sha256:" + sha256_hex(data) != version["content_digest"]:
            raise IntegrityViolation("the stored input no longer matches its recorded digest", code="digest_mismatch_at_rest")
        dest = self.d.db.get("destinations", run["destination_id"], tenant_id=tenant) if run.get("destination_id") else None
        dest_class = DestinationClass.parse(dest["klass"] if dest else (profile.destinations[0] if profile.destinations else "local_index"))
        baseline = self.baselines.approved_for(tenant, run["project_id"], run["profile_id"])
        av = self.d.scanner.scan(data)
        from ...slai.agent_policy import withheld_checks
        withheld = withheld_checks(plan, policy, inference_budget_left_cents=self.usage.inference_left_cents(tenant)) \
            if self.d.slai is not None else {}
        request = EngineRequest(
            data=data, profile=profile, policy=policy, filename=version.get("filename", ""),
            declared_media_type=version.get("media_type", ""), destination=dest_class,
            classification=DataClassification.parse(run.get("classification")), source_class=SourceClass.parse(run.get("source_class")),
            source_metadata=version.get("source_metadata") or {}, baseline=baseline["stats"] if baseline else None,
            known_revisions=self._known_revisions(run, version), av=av,
            document_reader=getattr(self.d.slai, "documents", None),
            limits=Limits(max_bytes=max(plan.max_run_bytes, 1), max_chars=self.d.settings.max_text_chars,
                          parse_timeout_s=float(self.d.settings.parse_timeout)),
            now=self.d.now(), withheld=withheld, run_id=rid)
        store = self.d.checkpoints.store_for(rid)
        stage_started = iso(self.d.now())

        def on_stage(stage: int, state: str, extra: dict[str, Any]) -> None:
            self._stage(rid, stage, "committed" if state in ("committed", "replayed") else state,
                        message="replayed from checkpoint" if state == "replayed" else "",
                        checkpoint=extra.get("checkpoint") or None,
                        metrics={k: v for k, v in extra.items() if k in ("checks", "ms", "decision")},
                        attempt=run["attempts"], started=stage_started)

        self._stage(rid, 2, "committed", message="normalised in an isolated process", attempt=run["attempts"])
        result = self.engine().evaluate(request, store, on_stage)
        o = result.outcome
        seen = {st["stage"] for st in self.d.db.find("run_stages", tenant_id=tenant, where={"run_id": rid}, limit=100)}
        for no in range(3, 15):                                  # a stage with nothing to run is shown, never silently absent
            if no not in seen:
                self._stage(rid, no, "skipped", message="no checks of this stage apply to this profile or input",
                            attempt=run["attempts"], started=stage_started)
        # ---- stage 14 output -> the authoritative Fitness Decision
        decision = FitnessDecision(
            id=new_id("dec"), tenant_id=tenant, project_id=run["project_id"], run_id=rid, decision=o.decision, status=o.status,
            disposition=o.disposition, reasons=o.reasons, rationale=o.rationale, policy_ref=f"{policy.id}@{run['policy_version']}",
            profile_ref=f"{profile.id}@{run['profile_version']}", input_digest=version["content_digest"],
            released_digest=version["content_digest"], coverage=o.coverage, created_at=self.d.now(), expires_at=o.expires_at,
            shadow=o.shadow, exception_ids=o.exception_ids, supersedes=None, decided_by="system", score=o.score)
        # ---- stage 15 disposition (review item / quarantine)
        self._stage(rid, 15, "committed", message=f"decision {o.decision.value}", attempt=run["attempts"])
        review = quarantine = None
        if decision.shadow:
            pass
        elif decision.decision == Decision.REVIEW:
            review = self._open_review(run, decision)
        if not decision.shadow and (decision.disposition == ArtifactDisposition.QUARANTINED or decision.decision == Decision.QUARANTINE):
            decision.disposition = ArtifactDisposition.QUARANTINED
            quarantine = self._quarantine(run, version, decision)
        # ---- stage 16 evidence
        artifacts = self._store_artifacts(run, version, result, decision, profile_doc, policy_doc, baseline)
        bundle = self._build_evidence(run, version, result, decision, policy, profile, baseline, request, stage_started)
        self._stage(rid, 16, "committed", message="evidence sealed", attempt=run["attempts"],
                    metrics={"seal": bundle.digest})
        # ---- persist decision + run
        self.d.db.put("decisions", {**decision.to_dict(), "id": decision.id, "schema": DECISION_SCHEMA}, tenant_id=tenant)
        run.update({"state": JobState.COMPLETED.value, "decision_id": decision.id, "decision": decision.decision.value,
                    "baseline_id": baseline["id"] if baseline else None, "finished_at": iso(self.d.now()), "error": "",
                    "evidence_seal": bundle.digest, "coverage_ok": bool(o.coverage.get("ok", True)) if isinstance(o.coverage, dict) else True,
                    "review_id": review["id"] if review else None, "quarantine_id": quarantine["id"] if quarantine else None,
                    "shadow": decision.shadow})
        self.d.db.put("runs", run, tenant_id=tenant)
        # ---- stage 17 audit
        audit_system(self.d, tenant, "run.decided", rid, {"decision": decision.decision.value, "policy": decision.policy_ref,
                                                          "profile": decision.profile_ref, "seal": bundle.digest[:24]})
        self._stage(rid, 17, "committed", message="audit event appended", attempt=run["attempts"])
        self._stage(rid, 18, "committed", message="stage outputs checkpointed", attempt=run["attempts"],
                    metrics={"store": getattr(self.d.checkpoints, "kind", "")})
        # ---- metering (idempotent per run+meter)
        cpu_ms = int((time.monotonic() - t0) * 1000)
        self.usage.record(tenant, rid, run["project_id"], METER_RUN, 1)
        self.usage.record(tenant, rid, run["project_id"], METER_SCAN_BYTES, billable_bytes(result.normalized.get("decoded_bytes", len(data))))
        cents = sum(int((r.metrics or {}).get("inference_cents", 0) or 0) for r in result.results.values())
        self.usage.record(tenant, rid, run["project_id"], METER_INFERENCE_CENTS, cents)
        self.usage.record(tenant, rid, run["project_id"], METER_CPU_MS, cpu_ms)
        # ---- stage 19 alerting
        self._alerts(run, decision, result)
        self._stage(rid, 19, "committed", message="alert rules evaluated", attempt=run["attempts"])
        # ---- stage 20 delivery
        self.delivery.plan(run, decision, dest, version)
        self._stage(rid, 20, "committed", message="delivery planned", attempt=run["attempts"])
        if self.d.slai is not None and not decision.shadow:
            self.d.slai.record_lineage(artifact_id=f"aidap-input-{version['content_digest'][-16:]}",
                                       digest=version["content_digest"], source_id=f"aidap-source-{run.get('source_class', 'unknown')}",
                                       parent_id=None, transformation=version.get("derivation") or "ingest",
                                       metadata={"run": rid, "decision": decision.decision.value})
        _ = artifacts

    # ------------------------------------------------------------------ review / quarantine records
    def _open_review(self, run: dict[str, Any], decision: FitnessDecision) -> dict[str, Any]:
        codes = sorted({r.code for r in decision.reasons if r.effect == Decision.REVIEW})
        prev = self.d.db.find("runs", tenant_id=run["tenant_id"], where={"asset_id": run["asset_id"], "decision": "pass",
                                                                         "state": "completed"}, limit=1)
        now = self.d.now()
        item = {"id": new_id("rev"), "tenant_id": run["tenant_id"], "project_id": run["project_id"], "run_id": run["id"],
                "decision_id": decision.id, "state": "open", "reason_codes": codes, "summary": decision.rationale.summary[:500],
                "created_at": iso(now), "assignee": "", "due_at": iso(now + timedelta(hours=72)), "resolved_by": "",
                "resolved_at": None, "resolution": "", "comment": "", "exception_id": "",
                "previous_run_id": prev[0]["id"] if prev else ""}
        self.d.db.insert("reviews", item, tenant_id=run["tenant_id"])
        return item

    def _quarantine(self, run: dict[str, Any], version: dict[str, Any], decision: FitnessDecision) -> dict[str, Any]:
        codes = sorted({r.code for r in decision.reasons if r.effect.rank >= Decision.QUARANTINE.rank})
        now = self.d.now()
        item = {"id": new_id("qua"), "tenant_id": run["tenant_id"], "project_id": run["project_id"], "run_id": run["id"],
                "version_id": version["id"], "blob_ref": version["blob_ref"], "reason_codes": codes, "created_at": iso(now),
                "retain_until": iso(now + timedelta(days=self.d.settings.quarantine_retention_days)), "state": "held",
                "last_accessed_by": "", "last_accessed_at": None, "disposed_by": "", "disposed_at": None}
        self.d.db.insert("quarantine", item, tenant_id=run["tenant_id"], ukey=f"{run['tenant_id']}:{run['id']}")
        return item

    # ------------------------------------------------------------------ evidence
    def _store_artifacts(self, run: dict[str, Any], version: dict[str, Any], result: Any, decision: FitnessDecision,
                         profile_doc: dict[str, Any], policy_doc: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
        doc = {"id": run["id"], "run_id": run["id"], "tenant_id": run["tenant_id"], "created_at": iso(self.d.now()),
               "normalized": result.normalized, "planned": [pc.to_dict() for pc in result.planned],
               "results": {cid: r.to_dict() for cid, r in result.results.items()},
               "confidence": result.confidence_summary, "stage_log": result.stage_log,
               "evaluators": [e.to_dict() for e in result.evaluators], "source_metadata": result.source_metadata,
               "column_stats": result.column_stats, "profile_doc": profile_doc, "policy_doc": policy_doc,
               "baseline_id": baseline["id"] if baseline else None,
               "destination": run.get("destination_id"), "classification": run.get("classification"),
               "source_class": run.get("source_class")}
        self.d.db.put("run_artifacts", to_jsonable(doc), tenant_id=run["tenant_id"])
        return doc

    def _build_evidence(self, run: dict[str, Any], version: dict[str, Any], result: Any, decision: FitnessDecision,
                        policy: Any, profile: Any, baseline: dict[str, Any] | None, request: EngineRequest,
                        started: str) -> EvidenceBundle:
        findings = [f.to_dict() for r in result.results.values() for f in r.findings]
        reviewers = [{"id": g["granted_by"], "role": g.get("granted_role", "")} for g in
                     self.d.db.find("grants", tenant_id=run["tenant_id"], where={"run_id": run["id"]}, limit=50)]
        prov = build_provenance(
            run_id=run["id"], tenant_id=run["tenant_id"], original_digest=version["content_digest"],
            normalized_digest=result.normalized.get("normalized_digest", ""), released_digest=decision.released_digest,
            policy_ref=decision.policy_ref, profile_ref=decision.profile_ref,
            baseline_ref=baseline["id"] if baseline else None,
            evaluators=[e.to_dict() for e in result.evaluators], reviewers=reviewers,
            derived_from_digest=None, started_at=started, ended_at=iso(self.d.now()))
        body = {
            "bundle_id": new_id("evb"), "tenant_id": run["tenant_id"], "run_id": run["id"], "project_id": run["project_id"],
            "created_at": iso(self.d.now()),
            "producer": {"name": "AIDAP", "version": __version__, "slai_baseline_commit": SLAI_BASELINE_COMMIT},
            "input": {"digest": version["content_digest"], "size": version["size"], "filename": version.get("filename", ""),
                      "media_type": result.normalized.get("media_type", ""), "normalized": result.normalized},
            "profile": {"ref": decision.profile_ref, "document": request.profile.to_dict()},
            "policy": {"ref": decision.policy_ref, "document": request.policy.to_dict()},
            "baseline": {"id": baseline["id"], "version": baseline["version"], "approved_by": baseline.get("approved_by_name", "")} if baseline else None,
            "evaluators": [e.to_dict() for e in result.evaluators],
            "coverage": decision.coverage, "findings": findings,
            "decision": decision.to_dict(), "confidence": result.confidence_summary, "stages": result.stage_log,
            "provenance": prov,
            "statement": ("Digests identify content and detect change; they do not prove authenticity. The seal detects "
                          "tampering after sealing; it is not a signature."),
        }
        bundle = EvidenceBundle(to_jsonable(body)).sealed()
        ref = self.d.blobs.put(f"{run['tenant_id']}/evidence/{run['id']}.json", bundle.to_json().encode("utf-8"))
        self.d.db.put("evidence", {"id": run["id"], "run_id": run["id"], "tenant_id": run["tenant_id"],
                                   "bundle_id": body["bundle_id"], "seal": bundle.digest, "blob_ref": ref,
                                   "created_at": iso(self.d.now()), "findings": len(findings)}, tenant_id=run["tenant_id"])
        return bundle

    # ------------------------------------------------------------------ alerts
    def _alerts(self, run: dict[str, Any], decision: FitnessDecision, result: Any) -> None:
        t, proj, rid = run["tenant_id"], run["project_id"], run["id"]
        codes = {r.code for r in decision.reasons}
        if decision.shadow:
            return
        if any(c.startswith("privacy.secret") for c in codes):
            self.alerts.raise_alert(t, proj, "credential_exposed", f"secret:{proj}", "A credential was found in an input",
                                    "The artifact was blocked and quarantined. Rotate the credential: it must be treated as exposed.",
                                    "critical", rid)
        if decision.decision == Decision.QUARANTINE or decision.disposition == ArtifactDisposition.QUARANTINED:
            self.alerts.raise_alert(t, proj, "quarantine", f"quarantine:{proj}", "An input was quarantined",
                                    decision.rationale.summary[:300], "high", rid)
            self._email_owner(t, f"AIDAP: input quarantined in project {proj}", decision.rationale.summary, f"q:{rid}")
        elif decision.decision == Decision.BLOCK:
            self.alerts.raise_alert(t, proj, "blocked", f"blocked:{proj}", "An input was blocked", decision.rationale.summary[:300],
                                    "high", rid)
        since = iso(self.d.now() - timedelta(hours=24))
        recent_bad = [r for r in self.d.db.find("runs", tenant_id=t, where={"project_id": proj, "decision": ["block", "quarantine"],
                                                                            "finished_at": (">=", since)}, limit=20)]
        if len(recent_bad) >= 3:
            self.alerts.raise_alert(t, proj, "repeated_failures", f"repeat:{proj}", "Repeated blocked or quarantined inputs",
                                    f"{len(recent_bad)} inputs in 24 hours; check the upstream source.", "high", rid)
        unresolved = [c for c, r in result.results.items() if not r.status.conclusive and r.mandatory]
        if unresolved:
            self.alerts.raise_alert(t, proj, "coverage_gap", f"gap:{proj}:{','.join(sorted(unresolved))[:60]}",
                                    "A mandatory check could not be completed",
                                    "Unresolved: " + ", ".join(sorted(unresolved)) + ". Inputs are held until this is fixed.",
                                    "medium", rid)

    def _email_owner(self, tenant_id: str, subject: str, body: str, dedupe: str) -> None:
        t = self.d.db.get("tenants", tenant_id, tenant_id=tenant_id) or {}
        if t.get("billing_email"):
            self.notify.email(tenant_id, t["billing_email"], subject, body[:1500], dedupe_key=dedupe)

    # ================================================================== re-decision after human review
    def redecide(self, run_id: str, grants: list[ExceptionGrant], *, decided_by: str, tenant_id: str) -> FitnessDecision:
        run = get_or_404(self.d, "runs", run_id, tenant_id, "run")
        art = get_or_404(self.d, "run_artifacts", run_id, tenant_id, "run results")
        old_doc = get_or_404(self.d, "decisions", run["decision_id"], tenant_id, "decision")
        old = FitnessDecision.from_dict(old_doc)
        profile, _, _ = self.d.configs.resolve(tenant_id, "profile", run["profile_id"], run["profile_version"])
        policy, _, _ = self.d.configs.resolve(tenant_id, "policy", run["policy_id"], run["policy_version"])
        results = {cid: CheckResult.from_dict(d) for cid, d in art["results"].items()}
        planned = [PlannedCheck(d["check_id"], d["mandatory"], d.get("enabled", True), d.get("skip_reason", ""))
                   for d in art["planned"]]
        dest = self.d.db.get("destinations", run["destination_id"], tenant_id=tenant_id) if run.get("destination_id") else None
        dest_class = DestinationClass.parse(dest["klass"] if dest else (profile.destinations[0] if profile.destinations else "local_index"))
        outcome = decide(results=results, planned=planned, policy=policy, profile=profile, destination=dest_class,
                         classification=DataClassification.parse(run.get("classification")),
                         source_class=run.get("source_class", "unknown"), grants=grants, now=self.d.now())
        new = FitnessDecision(
            id=new_id("dec"), tenant_id=tenant_id, project_id=run["project_id"], run_id=run_id, decision=outcome.decision,
            status=outcome.status,
            disposition=(ArtifactDisposition.QUARANTINED if old.disposition == ArtifactDisposition.QUARANTINED
                         else outcome.disposition), reasons=outcome.reasons, rationale=outcome.rationale, policy_ref=old.policy_ref,
            profile_ref=old.profile_ref, input_digest=old.input_digest, released_digest=old.released_digest,
            coverage=outcome.coverage, created_at=self.d.now(), expires_at=outcome.expires_at, shadow=outcome.shadow,
            exception_ids=[g.id for g in grants if g.active(self.d.now())], supersedes=old.id, decided_by=decided_by, score=outcome.score)
        old_doc["status"] = DecisionStatus.SUPERSEDED.value
        with self.d.db.transaction():
            self.d.db.put("decisions", old_doc, tenant_id=tenant_id)
            self.d.db.put("decisions", {**new.to_dict(), "schema": DECISION_SCHEMA}, tenant_id=tenant_id)
            run.update({"decision_id": new.id, "decision": new.decision.value})
            self.d.db.put("runs", run, tenant_id=tenant_id)
        audit_system(self.d, tenant_id, "run.redecided", run_id, {"from": old.decision.value, "to": new.decision.value,
                                                                  "exceptions": new.exception_ids}, actor=decided_by)
        version = get_or_404(self.d, "versions", run["version_id"], tenant_id, "input")
        self.delivery.plan(run, new, dest, version)
        return new
