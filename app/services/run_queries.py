"""Run reads and operator actions (cancel / retry / rerun / redact / release)."""

from __future__ import annotations

from typing import Any

from ...assurance_engine.evaluators.privacy.redact import redact_bytes
from ...contracts.versions import DECISION_SCHEMA
from ...domain.decisions import ArtifactDisposition, Decision, DecisionStatus, FitnessDecision, Reason
from ...domain.decisions.rationale import DecisionRationale
from ...domain.evidence import EvidenceBundle
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import Conflict, Forbidden, IntegrityViolation, NotFound, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id, sha256_hex
from ...domain.workflows.jobs import TERMINAL_JOB_STATES, JobState
from ..context import Principal
from ..utils.common import audit, audit_system, clean_page, get_or_404

__all__ = ["RunQueries"]

_SEV = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_PUBLIC_RUN_HIDE = ("idempotency_key",)


def chain(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order a run's decisions oldest to newest by following ``supersedes`` (timestamps can tie within a second)."""
    by_parent = {d.get("supersedes"): d for d in decisions}
    out, cur, seen = [], by_parent.get(None), set()
    while cur is not None and cur["id"] not in seen:
        out.append(cur)
        seen.add(cur["id"])
        cur = by_parent.get(cur["id"])
    return out + [d for d in decisions if d["id"] not in seen]


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k not in _PUBLIC_RUN_HIDE}


class RunQueries:
    d: Any
    usage: Any
    delivery: Any

    # ------------------------------------------------------------------ reads
    def list(self, p: Principal, *, project_id: str = "", decision: str = "", state: str = "", q: str = "",
             limit: Any = None, offset: Any = None) -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        lim, off = clean_page(limit, offset)
        where = {k: v for k, v in (("project_id", project_id), ("decision", decision), ("state", state)) if v}
        rows = self.d.db.find("runs", tenant_id=p.tenant_id, where=where or None, limit=lim + off + 400 if q else lim,
                              offset=0 if q else off)
        rows = [r for r in rows if p.can_project(r["project_id"])]
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in (r.get("filename", "") + " " + r.get("label", "") + " " + r["id"]).lower()]
            rows = rows[off:off + lim]
        total = self.d.db.count("runs", tenant_id=p.tenant_id, where=where or None)
        return {"items": [_public(r) for r in rows], "total": total, "limit": lim, "offset": off}

    def _run(self, p: Principal, run_id: str) -> dict[str, Any]:
        run = get_or_404(self.d, "runs", run_id, p.tenant_id, "run")
        p.require_project(run["project_id"])
        return run

    def get(self, p: Principal, run_id: str) -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        run = self._run(p, run_id)
        dec = self.d.db.get("decisions", run["decision_id"], tenant_id=p.tenant_id) if run.get("decision_id") else None
        out = _public(run)
        out["decision_detail"] = dec
        out["stages"] = self.stages(p, run_id)
        out["deliveries"] = [x for x in self.d.db.find("deliveries", tenant_id=p.tenant_id, where={"run_id": run_id}, limit=50)]
        out["history"] = chain(self.d.db.find("decisions", tenant_id=p.tenant_id, where={"run_id": run_id}, limit=50))
        out["release_authorized"] = bool(dec) and FitnessDecision.from_dict(dec).release_authorized(self.d.now(), None)
        return out

    def stages(self, p: Principal, run_id: str) -> list[dict[str, Any]]:
        p.require(Permission.RUNS_READ)
        self._run(p, run_id)
        return self.d.db.find("run_stages", tenant_id=p.tenant_id, where={"run_id": run_id}, order_by="stage", desc=False, limit=100)

    def findings(self, p: Principal, run_id: str, *, severity: str = "", check_id: str = "", category: str = "",
                 code: str = "") -> dict[str, Any]:
        p.require(Permission.FINDINGS_READ)
        self._run(p, run_id)
        art = self.d.db.get("run_artifacts", run_id, tenant_id=p.tenant_id)
        if art is None:
            return {"findings": [], "checks": [], "ready": False}
        floor = _SEV.get(severity, -1)
        checks, findings = [], []
        for cid, r in art["results"].items():
            checks.append({k: r[k] for k in ("check_id", "status", "evaluator", "origin", "mandatory", "coverage",
                                              "unknown_reason", "message", "duration_ms")} | {"findings": len(r["findings"])})
            for f in r["findings"]:
                if _SEV.get(f["severity"], 0) < floor or (check_id and cid != check_id) or \
                        (category and f["category"] != category) or (code and not f["code"].startswith(code)):
                    continue
                findings.append(f)
        findings.sort(key=lambda f: -_SEV.get(f["severity"], 0))
        return {"findings": findings, "checks": sorted(checks, key=lambda c: c["check_id"]), "ready": True,
                "confidence": art.get("confidence")}

    def decisions(self, p: Principal, run_id: str) -> list[dict[str, Any]]:
        p.require(Permission.RUNS_READ)
        self._run(p, run_id)
        return chain(self.d.db.find("decisions", tenant_id=p.tenant_id, where={"run_id": run_id}, limit=100))

    def evidence(self, p: Principal, run_id: str) -> dict[str, Any]:
        p.require(Permission.EVIDENCE_READ)
        run = self._run(p, run_id)
        meta = self.d.db.get("evidence", run_id, tenant_id=p.tenant_id)
        if meta is None:
            raise NotFound("evidence for this run is not available yet", code="evidence_pending")
        try:
            body = EvidenceBundle.from_dict(__import__("json").loads(self.d.blobs.get(meta["blob_ref"]).decode("utf-8")))
            ok = body.verify() and body.digest == meta["seal"]
        except Exception:                                              # noqa: BLE001
            body, ok = None, False
        if not ok:
            audit_system(self.d, p.tenant_id, "evidence.seal_invalid", run_id)
        return {"run_id": run_id, "verified": ok, "seal": meta["seal"], "bundle": body.to_dict() if body and ok else None,
                "note": None if ok else "The stored bundle failed verification and is withheld. Treat this run as untrusted."}

    def report_data(self, p: Principal, run_id: str) -> dict[str, Any]:
        from ...reporting import build_report
        run = self._run(p, run_id)
        p.require(Permission.RUNS_READ)
        p.require(Permission.FINDINGS_READ)
        dec = self.d.db.get("decisions", run["decision_id"], tenant_id=p.tenant_id) if run.get("decision_id") else None
        art = self.d.db.get("run_artifacts", run_id, tenant_id=p.tenant_id)
        if not dec or not art:
            raise Conflict("this run has no decision yet", code="run_not_decided")
        ev = self.d.db.get("evidence", run_id, tenant_id=p.tenant_id) or {}
        grants = self.d.db.find("grants", tenant_id=p.tenant_id, where={"run_id": run_id}, desc=False, limit=50)
        history = chain(self.d.db.find("decisions", tenant_id=p.tenant_id, where={"run_id": run_id}, limit=50))
        project = self.d.db.get("projects", run["project_id"], tenant_id=p.tenant_id) or {}
        return build_report(run=_public(run), decision=dec, artifacts=art, evidence=ev, grants=grants, history=history,
                            project=project, generated_at=iso(self.d.now()))

    def diff(self, p: Principal, run_id: str, other_id: str) -> dict[str, Any]:
        p.require(Permission.FINDINGS_READ)
        a, b = self._run(p, run_id), self._run(p, other_id)
        aa = self.d.db.get("run_artifacts", run_id, tenant_id=p.tenant_id)
        bb = self.d.db.get("run_artifacts", other_id, tenant_id=p.tenant_id)
        if not aa or not bb:
            raise Conflict("both runs need results to be compared", code="run_not_decided")

        def codes(art: dict[str, Any]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for r in art["results"].values():
                for f in r["findings"]:
                    cur = out.setdefault(f["code"], {"code": f["code"], "severity": f["severity"], "count": 0, "title": f["title"]})
                    cur["count"] += f.get("count", 1)
                    if _SEV.get(f["severity"], 0) > _SEV.get(cur["severity"], 0):
                        cur["severity"] = f["severity"]
            return out
        ca, cb = codes(aa), codes(bb)
        changed = [{"code": c, "from": ca[c], "to": cb[c]} for c in ca.keys() & cb.keys()
                   if ca[c]["count"] != cb[c]["count"] or ca[c]["severity"] != cb[c]["severity"]]
        stat = lambda r: {"status": r["status"], "coverage": r.get("coverage")}         # noqa: E731
        check_changes = [{"check_id": c, "from": stat(aa["results"][c]), "to": stat(bb["results"][c])}
                         for c in aa["results"].keys() & bb["results"].keys()
                         if aa["results"][c]["status"] != bb["results"][c]["status"]]
        return {"base": {"id": a["id"], "decision": a.get("decision"), "created_at": a["created_at"], "version_no": a.get("version_no")},
                "compare": {"id": b["id"], "decision": b.get("decision"), "created_at": b["created_at"], "version_no": b.get("version_no")},
                "findings_added": [cb[c] for c in sorted(cb.keys() - ca.keys())],
                "findings_resolved": [ca[c] for c in sorted(ca.keys() - cb.keys())],
                "findings_changed": sorted(changed, key=lambda x: x["code"]),
                "check_status_changes": sorted(check_changes, key=lambda x: x["check_id"]),
                "decision_changed": a.get("decision") != b.get("decision")}

    # ------------------------------------------------------------------ actions
    def cancel(self, p: Principal, run_id: str) -> dict[str, Any]:
        p.require(Permission.RUNS_MANAGE)
        run = self._run(p, run_id)
        if JobState(run["state"]) in TERMINAL_JOB_STATES:
            raise Conflict(f"this run is already {run['state']}", code="run_terminal")
        self.d.queue.cancel(f"run:{run_id}")
        run.update({"state": JobState.CANCELLED.value, "finished_at": iso(self.d.now())})
        self.d.db.put("runs", run, tenant_id=p.tenant_id)
        audit(self.d, p, "run.cancelled", run_id)
        return _public(run)

    def retry(self, p: Principal, run_id: str) -> dict[str, Any]:
        p.require(Permission.RUNS_MANAGE)
        run = self._run(p, run_id)
        if run["state"] not in (JobState.FAILED.value, JobState.CANCELLED.value):
            raise Conflict("only a failed or cancelled run can be retried", code="not_retryable")
        run.update({"state": JobState.QUEUED.value, "attempts": 0, "error": "", "finished_at": None})
        self.d.db.put("runs", run, tenant_id=p.tenant_id)
        self.d.checkpoints.drop(run_id)
        self.d.queue.enqueue("run", {"run_id": run_id, "tenant_id": p.tenant_id}, dedupe_key=f"run:{run_id}",
                             max_attempts=self.d.settings.max_attempts)
        audit(self.d, p, "run.retried", run_id)
        return _public(run)

    def rerun(self, p: Principal, run_id: str, *, latest: bool = True) -> dict[str, Any]:
        """A new run of the same input under the *current* published configuration. History is never rewritten."""
        p.require(Permission.RUNS_MANAGE)
        run = self._run(p, run_id)
        ver = get_or_404(self.d, "versions", run["version_id"], p.tenant_id, "input")
        if ver.get("purged"):
            raise Conflict("the input of this run was purged by retention and cannot be re-run", code="input_purged")
        data = self.d.blobs.get(ver["blob_ref"])
        if "sha256:" + sha256_hex(data) != ver["content_digest"]:
            raise IntegrityViolation("stored input does not match its digest", code="digest_mismatch_at_rest")
        return self.submit(p, project_id=run["project_id"], data=data, filename=ver.get("filename", ""),
                           media_type=ver.get("media_type", ""), profile_id=run["profile_id"],
                           policy_id=run["policy_id"], destination_id=run.get("destination_id") or "",
                           source_class=run.get("source_class", "unknown"), classification=run.get("classification", "internal"),
                           label=run.get("label", ""), asset_name=run.get("asset_name", ""), metadata=ver.get("source_metadata"),
                           source="rerun", parent_run_id=run_id)

    def redact(self, p: Principal, run_id: str, types: list[str] | None = None) -> dict[str, Any]:
        """Produce a *derivative* (never an overwrite) with PII spans masked, and re-assure it as a new run."""
        p.require(Permission.RUNS_MANAGE)
        run = self._run(p, run_id)
        ver = get_or_404(self.d, "versions", run["version_id"], p.tenant_id, "input")
        if ver.get("purged"):
            raise Conflict("the input was purged by retention", code="input_purged")
        q = self.d.db.get_by_ukey("quarantine", f"{p.tenant_id}:{run_id}")
        if q and q["state"] == "held":
            p.require(Permission.QUARANTINE_ACCESS)                   # redacting reads the quarantined content
        data = self.d.blobs.get(ver["blob_ref"])
        new_data, stats = redact_bytes(data, types)
        if not stats.get("total"):
            raise Conflict("nothing to redact: no spans of the selected types were found", code="nothing_to_redact")
        new = self.submit(p, project_id=run["project_id"], data=new_data, filename=ver.get("filename", ""),
                          media_type=ver.get("media_type", ""), profile_id=run["profile_id"], policy_id=run["policy_id"],
                          destination_id=run.get("destination_id") or "", source_class=run.get("source_class", "unknown"),
                          classification=run.get("classification", "internal"), label=(run.get("label", "") + " (redacted)").strip(),
                          asset_name=run.get("asset_name", ""), metadata=ver.get("source_metadata"), source="redaction",
                          parent_run_id=run_id, derived_from=ver["id"], derivation="redaction")
        audit(self.d, p, "run.redacted", run_id, {"new_run": new["id"], **{"redacted_total": stats.get("total", 0)}})
        return {"run": new, "redaction": stats}

    def reject(self, run_id: str, *, decided_by: str, tenant_id: str, justification: str) -> FitnessDecision:
        """A reviewer's rejection supersedes REVIEW with BLOCK. Humans may only ever tighten a decision this way."""
        run = get_or_404(self.d, "runs", run_id, tenant_id, "run")
        old_doc = get_or_404(self.d, "decisions", run["decision_id"], tenant_id, "decision")
        old = FitnessDecision.from_dict(old_doc)
        reason = Reason("review.rejected", f"Rejected in human review: {justification[:300]}", Decision.BLOCK,
                        waivable=False, guidance="Repair the input and submit it again.")
        new = FitnessDecision(
            id=new_id("dec"), tenant_id=tenant_id, project_id=old.project_id, run_id=run_id, decision=Decision.BLOCK,
            status=DecisionStatus.ACTIVE, disposition=ArtifactDisposition.RETAINED, reasons=[*old.reasons, reason],
            rationale=old.rationale, policy_ref=old.policy_ref, profile_ref=old.profile_ref, input_digest=old.input_digest,
            released_digest=old.released_digest, coverage=old.coverage, created_at=self.d.now(), expires_at=None,
            shadow=old.shadow, exception_ids=[], supersedes=old.id, decided_by=decided_by, score=old.score)
        old_doc["status"] = DecisionStatus.SUPERSEDED.value
        with self.d.db.transaction():
            self.d.db.put("decisions", old_doc, tenant_id=tenant_id)
            self.d.db.put("decisions", {**new.to_dict(), "schema": DECISION_SCHEMA}, tenant_id=tenant_id)
            run.update({"decision_id": new.id, "decision": "block"})
            self.d.db.put("runs", run, tenant_id=tenant_id)
        audit_system(self.d, tenant_id, "run.rejected", run_id, {"by": decided_by}, actor=decided_by)
        dest = self.d.db.get("destinations", run["destination_id"], tenant_id=tenant_id) if run.get("destination_id") else None
        ver = self.d.db.get("versions", run["version_id"], tenant_id=tenant_id) or {}
        self.delivery.plan(run, new, dest, ver)
        return new

    def artifact(self, p: Principal, run_id: str) -> tuple[bytes, dict[str, Any]]:
        """Pull delivery. The single release gate: an ACTIVE, unexpired, non-shadow PASS for exactly this digest."""
        p.require(Permission.RUNS_READ)
        run = self._run(p, run_id)
        if not run.get("decision_id"):
            raise Forbidden("this run has no decision, so nothing is authorised for release", code="release_not_authorized")
        dec = FitnessDecision.from_dict(get_or_404(self.d, "decisions", run["decision_id"], p.tenant_id, "decision"))
        ver = get_or_404(self.d, "versions", run["version_id"], p.tenant_id, "input")
        if not dec.release_authorized(self.d.now(), ver["content_digest"]):
            audit(self.d, p, "artifact.pull_denied", run_id, {"decision": dec.decision.value, "status": dec.status.value})
            raise Forbidden(f"release is not authorised (decision {dec.decision.value}, status {dec.status.value})",
                            code="release_not_authorized")
        if ver.get("purged"):
            raise Conflict("the artifact was purged by retention", code="input_purged")
        data = self.d.blobs.get(ver["blob_ref"])
        if "sha256:" + sha256_hex(data) != dec.released_digest:
            raise IntegrityViolation("the stored artifact no longer matches the digest that was assured",
                                     code="digest_mismatch_at_release")
        self.delivery.record_pull(p, run, dec)
        return data, ver
