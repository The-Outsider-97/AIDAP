"""Human review (stage 15) and quarantine custody. Exceptions are attributable, scoped to specific reason codes,
justified and expiring; non-waivable codes can never be waived; the submitter cannot approve their own run when
another eligible reviewer exists."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...domain.accounts.plans import F_REVIEW_ROLES
from ...domain.decisions import ExceptionGrant, exception_allowed_for
from ...domain.governance.authorization import Permission, ROLE_PERMISSIONS, Role
from ...domain.utils.domain_errors import Conflict, Forbidden, NotFound, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id, parse_iso
from ..context import Principal
from ..utils.common import audit, audit_system, clean_page, get_or_404

__all__ = ["ReviewService", "QuarantineService"]

MAX_EXCEPTION_DAYS = 90
DEFAULT_EXCEPTION_DAYS = 30
ACCESS_WINDOW_MINUTES = 15


class ReviewService:
    def __init__(self, deps: Any, plans: Any, runs: Any) -> None:
        self.d, self.plans, self.runs = deps, plans, runs

    def list(self, p: Principal, state: str = "", project_id: str = "", assignee: str = "", limit: Any = None,
             offset: Any = None) -> list[dict[str, Any]]:
        p.require(Permission.REVIEWS_READ)
        lim, off = clean_page(limit, offset)
        where = {k: v for k, v in (("state", state), ("project_id", project_id), ("assignee", assignee)) if v}
        return [r for r in self.d.db.find("reviews", tenant_id=p.tenant_id, where=where or None, limit=lim, offset=off)
                if p.can_project(r["project_id"])]

    def get(self, p: Principal, review_id: str) -> dict[str, Any]:
        p.require(Permission.REVIEWS_READ)
        r = get_or_404(self.d, "reviews", review_id, p.tenant_id, "review")
        p.require_project(r["project_id"])
        run = self.d.db.get("runs", r["run_id"], tenant_id=p.tenant_id) or {}
        dec = self.d.db.get("decisions", run.get("decision_id", ""), tenant_id=p.tenant_id) or {}
        art = self.d.db.get("run_artifacts", r["run_id"], tenant_id=p.tenant_id) or {}
        findings = [f for res in (art.get("results") or {}).values() for f in res.get("findings", [])
                    if f["code"] in set(r.get("reason_codes", [])) or f["severity"] in ("high", "critical")]
        grants = self.d.db.find("grants", tenant_id=p.tenant_id, where={"review_id": review_id}, limit=20)
        return {**r, "run": {k: run.get(k) for k in ("id", "filename", "label", "decision", "created_at", "created_by",
                                                       "profile_id", "policy_id", "destination_id", "project_id")},
                "decision_detail": dec, "findings": findings[:200], "grants": grants,
                "waivable": {c: exception_allowed_for(c) for c in r.get("reason_codes", [])}}

    def _eligible(self, tenant_id: str, exclude_user: str) -> int:
        n = 0
        for m in self.d.db.find("memberships", tenant_id=tenant_id, limit=1000):
            if m["user_id"] != exclude_user and m.get("status", "active") == "active" and \
                    Permission.REVIEWS_RESOLVE in ROLE_PERMISSIONS[Role(m["role"])] and m["role"] != "viewer":
                n += 1
        return n

    def assign(self, p: Principal, review_id: str, assignee: str) -> dict[str, Any]:
        p.require(Permission.REVIEWS_RESOLVE)
        r = get_or_404(self.d, "reviews", review_id, p.tenant_id, "review")
        p.require_project(r["project_id"])
        if r["state"] != "open":
            raise Conflict("this review is already resolved", code="review_closed")
        m = self.d.db.get_by_ukey("memberships", f"{p.tenant_id}:{assignee}")
        if m is None or Permission.REVIEWS_RESOLVE not in ROLE_PERMISSIONS[Role(m["role"])]:
            raise ValidationFailed("the assignee is not a member who can resolve reviews", details={"fields": {"assignee": "ineligible"}})
        r["assignee"] = assignee
        self.d.db.put("reviews", r, tenant_id=p.tenant_id)
        audit(self.d, p, "review.assigned", review_id, {"assignee": assignee})
        return r

    def resolve(self, p: Principal, review_id: str, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.REVIEWS_RESOLVE)
        r = get_or_404(self.d, "reviews", review_id, p.tenant_id, "review")
        p.require_project(r["project_id"])
        if r["state"] != "open":
            raise Conflict("this review is already resolved", code="review_closed")
        run = get_or_404(self.d, "runs", r["run_id"], p.tenant_id, "run")
        action, comment = data["resolution"], (data.get("comment") or "").strip()
        now = self.d.now()
        if action == "approve_exception":
            self.plans.require_feature(p.tenant_id, F_REVIEW_ROLES, "Review exceptions")
            if len(comment) < 10:
                raise ValidationFailed("an exception needs a written justification (at least 10 characters)",
                                       details={"fields": {"comment": "justification required"}})
            codes = list(data.get("reason_codes") or r["reason_codes"])
            unknown = [c for c in codes if c not in r["reason_codes"]]
            if unknown or not codes:
                raise ValidationFailed("exceptions can only cover this review's own reason codes",
                                       details={"fields": {"reason_codes": f"not part of this review: {unknown}"}})
            blocked = [c for c in codes if not exception_allowed_for(c)]
            if blocked:
                raise Forbidden("these reasons can never be waived: " + ", ".join(blocked), code="non_waivable",
                                details={"codes": blocked})
            if run["created_by"] in (p.actor, p.id) and self._eligible(p.tenant_id, p.id) > 0:
                raise Forbidden("a different reviewer must approve an exception for an input you submitted "
                                "(segregation of duties)", code="segregation_of_duties")
            days = max(1, min(int(data.get("days") or DEFAULT_EXCEPTION_DAYS), MAX_EXCEPTION_DAYS))
            grant = ExceptionGrant(new_id("exc"), p.tenant_id, run["id"], review_id, codes, p.actor, p.role, comment, now,
                                   now + timedelta(days=days))
            gd = grant.to_dict()
            gd["project_id"] = run["project_id"]
            with self.d.db.transaction():
                self.d.db.insert("grants", gd, tenant_id=p.tenant_id)
                r.update({"state": "resolved", "resolution": action, "comment": comment, "resolved_by": p.actor,
                          "resolved_at": iso(now), "exception_id": grant.id})
                self.d.db.put("reviews", r, tenant_id=p.tenant_id)
                grants = [ExceptionGrant.from_dict(g) for g in self.d.db.find("grants", tenant_id=p.tenant_id,
                                                                              where={"run_id": run["id"]}, limit=100)]
                new = self.runs.redecide(run["id"], grants, decided_by=p.actor, tenant_id=p.tenant_id)
            audit(self.d, p, "review.exception_granted", review_id, {"exception": grant.id, "codes": codes, "days": days,
                                                                     "new_decision": new.decision.value})
            return {**r, "decision": new.decision.value, "exception": gd}
        if action == "reject":
            if len(comment) < 3:
                raise ValidationFailed("say why the input is rejected", details={"fields": {"comment": "required"}})
            with self.d.db.transaction():
                r.update({"state": "resolved", "resolution": action, "comment": comment, "resolved_by": p.actor,
                          "resolved_at": iso(now)})
                self.d.db.put("reviews", r, tenant_id=p.tenant_id)
                new = self.runs.reject(run["id"], decided_by=p.actor, tenant_id=p.tenant_id, justification=comment)
            audit(self.d, p, "review.rejected", review_id, {"new_decision": new.decision.value})
            return {**r, "decision": new.decision.value}
        # request_repair: the input should be redacted/fixed and re-submitted; the decision stands.
        r.update({"state": "resolved", "resolution": action, "comment": comment, "resolved_by": p.actor, "resolved_at": iso(now)})
        self.d.db.put("reviews", r, tenant_id=p.tenant_id)
        audit(self.d, p, "review.repair_requested", review_id)
        return {**r, "decision": run.get("decision")}

    def revoke_exception(self, p: Principal, exception_id: str) -> dict[str, Any]:
        p.require(Permission.REVIEWS_RESOLVE)
        g = get_or_404(self.d, "grants", exception_id, p.tenant_id, "exception")
        p.require_project(g.get("project_id", ""))
        if g.get("revoked"):
            raise Conflict("already revoked", code="already_revoked")
        g["revoked"] = True
        self.d.db.put("grants", g, tenant_id=p.tenant_id)
        grants = [ExceptionGrant.from_dict(x) for x in self.d.db.find("grants", tenant_id=p.tenant_id,
                                                                      where={"run_id": g["run_id"]}, limit=100)]
        new = self.runs.redecide(g["run_id"], grants, decided_by=p.actor, tenant_id=p.tenant_id)
        audit(self.d, p, "review.exception_revoked", exception_id, {"new_decision": new.decision.value})
        return {"exception_id": exception_id, "decision": new.decision.value}

    def sweep_expired(self) -> int:
        """Exceptions expire: re-decide runs whose grants lapsed so a stale PASS cannot be released."""
        now, n = self.d.now(), 0
        for g in self.d.db.find("grants", where={"revoked": False, "expired_handled": None}, limit=500):
            if parse_iso(g["expires_at"]) > now:
                continue
            g["expired_handled"] = True
            self.d.db.put("grants", g, tenant_id=g["tenant_id"])
            grants = [ExceptionGrant.from_dict(x) for x in self.d.db.find("grants", tenant_id=g["tenant_id"],
                                                                          where={"run_id": g["run_id"]}, limit=100)]
            try:
                self.runs.redecide(g["run_id"], grants, decided_by="system", tenant_id=g["tenant_id"])
                audit_system(self.d, g["tenant_id"], "review.exception_expired", g["id"])
                n += 1
            except Exception:                                           # noqa: BLE001
                continue
        return n


class QuarantineService:
    def __init__(self, deps: Any) -> None:
        self.d = deps

    def list(self, p: Principal, state: str = "", limit: Any = None, offset: Any = None) -> list[dict[str, Any]]:
        p.require(Permission.REVIEWS_READ)
        lim, off = clean_page(limit, offset)
        where = {"state": state} if state else None
        return [{k: v for k, v in q.items() if k != "blob_ref"} for q in
                self.d.db.find("quarantine", tenant_id=p.tenant_id, where=where, limit=lim, offset=off)
                if p.can_project(q["project_id"])]

    def get(self, p: Principal, qid: str) -> dict[str, Any]:
        p.require(Permission.REVIEWS_READ)
        q = get_or_404(self.d, "quarantine", qid, p.tenant_id, "quarantined item")
        p.require_project(q["project_id"])
        return {k: v for k, v in q.items() if k != "blob_ref"}

    def access(self, p: Principal, qid: str, purpose: str) -> dict[str, Any]:
        """Quarantine content is a separate permission with a stated purpose; every access is audited."""
        p.require(Permission.QUARANTINE_ACCESS)
        q = get_or_404(self.d, "quarantine", qid, p.tenant_id, "quarantined item")
        p.require_project(q["project_id"])
        if q["state"] != "held":
            raise Conflict("this item has already been disposed of", code="not_held")
        now = self.d.now()
        grant = {"id": new_id("qac"), "tenant_id": p.tenant_id, "quarantine_id": qid, "user_id": p.id, "purpose": purpose,
                 "created_at": iso(now), "expires_at": iso(now + timedelta(minutes=ACCESS_WINDOW_MINUTES))}
        self.d.db.insert("quarantine_access", grant, tenant_id=p.tenant_id)
        q["last_accessed_by"], q["last_accessed_at"] = p.actor, iso(now)
        self.d.db.put("quarantine", q, tenant_id=p.tenant_id)
        audit(self.d, p, "quarantine.access_granted", qid, {"purpose": purpose})
        return {"access_id": grant["id"], "expires_at": grant["expires_at"], "window_minutes": ACCESS_WINDOW_MINUTES}

    def fetch(self, p: Principal, qid: str, access_id: str) -> tuple[bytes, str]:
        p.require(Permission.QUARANTINE_ACCESS)
        g = self.d.db.get("quarantine_access", access_id, tenant_id=p.tenant_id)
        if g is None or g["quarantine_id"] != qid or g["user_id"] != p.id or parse_iso(g["expires_at"]) <= self.d.now():
            raise Forbidden("request access with a stated purpose first (access windows are short)", code="access_required")
        q = get_or_404(self.d, "quarantine", qid, p.tenant_id, "quarantined item")
        if q["state"] != "held":
            raise Conflict("this item has already been disposed of", code="not_held")
        audit(self.d, p, "quarantine.content_fetched", qid)
        return self.d.blobs.get(q["blob_ref"]), q["run_id"]

    def dispose(self, p: Principal, qid: str, action: str, comment: str) -> dict[str, Any]:
        p.require(Permission.QUARANTINE_DISPOSE)
        q = get_or_404(self.d, "quarantine", qid, p.tenant_id, "quarantined item")
        p.require_project(q["project_id"])
        if q["state"] != "held":
            raise Conflict("this item has already been disposed of", code="not_held")
        if action == "delete":
            self._purge(q)
            q["state"] = "deleted"
        else:
            q["state"] = "released_for_investigation"        # custody ends; decision is NOT changed and is not a release
        q.update({"disposed_by": p.actor, "disposed_at": iso(self.d.now()), "disposal_comment": comment})
        self.d.db.put("quarantine", q, tenant_id=p.tenant_id)
        audit(self.d, p, "quarantine.disposed", qid, {"action": action, "comment": comment})
        return {k: v for k, v in q.items() if k != "blob_ref"}

    def _purge(self, q: dict[str, Any]) -> None:
        try:
            self.d.blobs.delete(q["blob_ref"])
        except Exception:                                               # noqa: BLE001
            pass
        v = self.d.db.get("versions", q["version_id"], tenant_id=q["tenant_id"])
        if v:
            v["purged"] = True
            self.d.db.put("versions", v, tenant_id=q["tenant_id"])

    def sweep(self) -> int:
        """Retention: held items past their window are deleted (never silently released)."""
        now, n = self.d.now(), 0
        for q in self.d.db.find("quarantine", where={"state": "held", "retain_until": ("<", iso(now))}, limit=500):
            self._purge(q)
            q.update({"state": "deleted", "disposed_by": "system", "disposed_at": iso(now), "disposal_comment": "retention window elapsed"})
            self.d.db.put("quarantine", q, tenant_id=q["tenant_id"])
            audit_system(self.d, q["tenant_id"], "quarantine.expired", q["id"])
            n += 1
        return n
