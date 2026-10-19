"""Projects, destinations, baselines, alerts, audit queries and schedules."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

from ...assurance_engine.evaluators.quality.population import build_baseline_stats
from ...assurance_engine.normalization import normalize
from ...domain.accounts.plans import F_AUDIT_EXPORT, F_OBJECT_STORE, F_SCHEDULES, F_WEBHOOKS
from ...domain.data.classification import DeliveryKind, DestinationClass
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import Conflict, Forbidden, NotFound, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id, parse_iso, slugify
from ...reporting.csv_export import csv_safe
from ..context import Principal
from ..utils.common import audit, clean_page, get_or_404, sanitize_doc
from .plans import PlanService

__all__ = ["ProjectService", "DestinationService", "BaselineService", "AlertService", "AuditQueries", "ScheduleService",
           "csv_safe"]


class ProjectService:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    def list(self, p: Principal, include_archived: bool = False) -> list[dict[str, Any]]:
        where: dict[str, Any] = {} if include_archived else {"archived": False}
        out = [x for x in self.d.db.find("projects", tenant_id=p.tenant_id, where=where, order_by="created_at", desc=False,
                                         limit=500) if p.can_project(x["id"])]
        for x in out:
            x["run_count"] = self.d.db.count("runs", tenant_id=p.tenant_id, where={"project_id": x["id"]})
        return out

    def get(self, p: Principal, project_id: str) -> dict[str, Any]:
        p.require_project(project_id)
        return get_or_404(self.d, "projects", project_id, p.tenant_id, "project")

    def create(self, p: Principal, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.PROJECTS_MANAGE)
        self.plans.enforce_project_limit(p.tenant_id)
        self._validate_refs(p, data)
        slug = slugify(data["name"], "project")
        if self.d.db.count("projects", tenant_id=p.tenant_id, where={"slug": slug}):
            slug = f"{slug}-{new_id('x')[-4:]}"
        rec = {"id": new_id("prj"), "tenant_id": p.tenant_id, "name": data["name"], "slug": slug,
               "created_at": iso(self.d.now()), "description": data.get("description", ""),
               "default_profile_id": data.get("default_profile_id", ""), "default_policy_id": data.get("default_policy_id") or "standard",
               "default_destination_id": data.get("default_destination_id", ""), "archived": False}
        self.d.db.insert("projects", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "project.created", rec["id"], {"name": rec["name"]})
        return rec

    def _validate_refs(self, p: Principal, data: dict[str, Any]) -> None:
        for key, kind in (("default_profile_id", "profile"), ("default_policy_id", "policy")):
            cid = data.get(key)
            if cid:
                self.d.configs.resolve(p.tenant_id, kind, cid)
        dest = data.get("default_destination_id")
        if dest:
            get_or_404(self.d, "destinations", dest, p.tenant_id, "destination")

    def update(self, p: Principal, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.PROJECTS_MANAGE)
        rec = self.get(p, project_id)
        self._validate_refs(p, data)
        if data.get("archived") is False and rec.get("archived"):
            self.plans.enforce_project_limit(p.tenant_id)
        for k, v in data.items():
            if k in ("name", "description", "default_profile_id", "default_policy_id", "default_destination_id", "archived"):
                if v is not None and not (isinstance(v, str) and v == "" and k in ("name", "default_policy_id")):
                    rec[k] = v
        self.d.db.put("projects", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "project.updated", project_id, {k: v for k, v in data.items() if k != "description"})
        return rec


class DestinationService:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    @staticmethod
    def public(rec: dict[str, Any]) -> dict[str, Any]:
        out = sanitize_doc(rec)
        out["has_secret"] = bool(rec.get("secret_sealed"))
        out.pop("secret_sealed", None)
        return out

    def list(self, p: Principal, project_id: str = "") -> list[dict[str, Any]]:
        p.require(Permission.POLICIES_READ)
        where = {"project_id": project_id} if project_id else None
        return [self.public(x) for x in self.d.db.find("destinations", tenant_id=p.tenant_id, where=where,
                                                       order_by="created_at", desc=False, limit=500)]

    def _check_delivery(self, p: Principal, delivery: str, target: str) -> None:
        if delivery == DeliveryKind.WEBHOOK.value:
            self.plans.require_feature(p.tenant_id, F_WEBHOOKS, "Signed webhooks")
            if not target:
                raise ValidationFailed("a webhook destination needs a target URL", details={"fields": {"target_url": "required"}})
            try:
                self.d.webhooks.validate_target(target)
            except Exception as exc:                                  # noqa: BLE001
                raise ValidationFailed(f"the webhook target was rejected: {exc}", details={"fields": {"target_url": str(exc)[:200]}}) from exc
        elif delivery == DeliveryKind.OBJECT_STORE.value:
            self.plans.require_feature(p.tenant_id, F_OBJECT_STORE, "Object-store delivery")
            if not target or target.startswith(("/", "..")) or ".." in target.split("/"):
                raise ValidationFailed("object-store delivery needs a relative key prefix", details={"fields": {"target_url": "invalid prefix"}})

    def create(self, p: Principal, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.DESTINATIONS_MANAGE)
        self._check_delivery(p, data["delivery"], data.get("target_url", ""))
        did = new_id("dst")
        rec = {"id": did, "tenant_id": p.tenant_id, "project_id": data.get("project_id", ""), "name": data["name"],
               "klass": data["klass"], "created_at": iso(self.d.now()), "delivery": data["delivery"],
               "target_url": data.get("target_url", ""), "secret_sealed": "", "enabled": True,
               "description": data.get("description", "")}
        if data.get("secret"):
            rec["secret_sealed"] = self.d.box.seal(data["secret"].encode(), aad=did.encode())
        elif data["delivery"] == DeliveryKind.WEBHOOK.value:
            import secrets as _s
            generated = "whsec_" + _s.token_urlsafe(32)
            rec["secret_sealed"] = self.d.box.seal(generated.encode(), aad=did.encode())
            rec["_generated_secret"] = generated
        self.d.db.insert("destinations", {k: v for k, v in rec.items() if k != "_generated_secret"}, tenant_id=p.tenant_id)
        audit(self.d, p, "destination.created", did, {"klass": rec["klass"], "delivery": rec["delivery"]})
        out = self.public(rec)
        out.pop("_generated_secret", None)
        if rec.get("_generated_secret"):
            out["signing_secret"] = rec["_generated_secret"]            # shown exactly once
        return out

    def update(self, p: Principal, dest_id: str, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.DESTINATIONS_MANAGE)
        rec = get_or_404(self.d, "destinations", dest_id, p.tenant_id, "destination")
        delivery = data.get("delivery") or rec["delivery"]
        target = data.get("target_url", rec["target_url"]) if "target_url" in data else rec["target_url"]
        if delivery != rec["delivery"] or "target_url" in data:
            self._check_delivery(p, delivery, target)
        for k in ("name", "klass", "delivery", "target_url", "description", "enabled"):
            if data.get(k) not in (None, ""):
                rec[k] = data[k]
            elif k == "target_url" and k in data:
                rec[k] = ""
        if data.get("secret"):
            rec["secret_sealed"] = self.d.box.seal(data["secret"].encode(), aad=dest_id.encode())
        self.d.db.put("destinations", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "destination.updated", dest_id)
        return self.public(rec)

    def delete(self, p: Principal, dest_id: str) -> None:
        p.require(Permission.DESTINATIONS_MANAGE)
        if self.d.db.count("runs", tenant_id=p.tenant_id, where={"destination_id": dest_id}):
            rec = get_or_404(self.d, "destinations", dest_id, p.tenant_id, "destination")
            rec["enabled"] = False                                    # referenced by history: disable, never erase
            self.d.db.put("destinations", rec, tenant_id=p.tenant_id)
            audit(self.d, p, "destination.disabled", dest_id)
            return
        if not self.d.db.delete("destinations", dest_id, tenant_id=p.tenant_id):
            raise NotFound("destination not found")
        audit(self.d, p, "destination.deleted", dest_id)


class BaselineService:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    def list(self, p: Principal, project_id: str = "", profile_id: str = "") -> list[dict[str, Any]]:
        p.require(Permission.RUNS_READ)
        where = {k: v for k, v in (("project_id", project_id), ("profile_id", profile_id)) if v}
        return [{k: v for k, v in b.items() if k != "stats"} | {"columns": len((b.get("stats") or {}).get("columns", {}))}
                for b in self.d.db.find("baselines", tenant_id=p.tenant_id, where=where or None, limit=200)]

    def get(self, p: Principal, baseline_id: str) -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        return get_or_404(self.d, "baselines", baseline_id, p.tenant_id, "baseline")

    def approved_for(self, tenant_id: str, project_id: str, profile_id: str) -> dict[str, Any] | None:
        found = self.d.db.find("baselines", tenant_id=tenant_id,
                               where={"project_id": project_id, "profile_id": profile_id, "status": "approved"},
                               order_by="version", limit=1)
        return found[0] if found else None

    def propose(self, p: Principal, run_id: str, name: str = "") -> dict[str, Any]:
        p.require(Permission.BASELINES_PROPOSE)
        run = get_or_404(self.d, "runs", run_id, p.tenant_id, "run")
        p.require_project(run["project_id"])
        if run["state"] != "completed":
            raise Conflict("a baseline can only be proposed from a completed run", code="run_not_completed")
        ver = get_or_404(self.d, "versions", run["version_id"], p.tenant_id, "input")
        if ver.get("purged"):
            raise Conflict("the input of this run has been purged by retention", code="input_purged")
        data = self.d.blobs.get(ver["blob_ref"])
        norm = normalize(data, filename=ver.get("filename", ""), declared_media_type=ver.get("media_type", ""),
                         isolate=True)
        if not norm.is_records or not norm.records:
            raise ValidationFailed("only tabular inputs (CSV/JSON/JSONL records) can serve as a baseline")
        stats = build_baseline_stats(norm)
        version = 1 + max([b["version"] for b in self.d.db.find("baselines", tenant_id=p.tenant_id, where={
            "project_id": run["project_id"], "profile_id": run["profile_id"]}, limit=500)] or [0])
        rec = {"id": new_id("bln"), "tenant_id": p.tenant_id, "project_id": run["project_id"], "profile_id": run["profile_id"],
               "name": name or f"{run['profile_id']} baseline v{version}", "version": version, "status": "proposed",
               "stats": stats, "sample_size": stats["sample_size"], "proposed_by": p.id, "proposed_by_name": p.actor,
               "created_at": iso(self.d.now()), "source_run_id": run_id, "schema_signature": stats.get("schema_signature", ""),
               "approved_by": "", "approved_at": None, "retired_at": None}
        self.d.db.insert("baselines", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "baseline.proposed", rec["id"], {"run": run_id, "sample": rec["sample_size"]})
        return {k: v for k, v in rec.items() if k != "stats"}

    def approve(self, p: Principal, baseline_id: str) -> dict[str, Any]:
        p.require(Permission.BASELINES_APPROVE)
        b = get_or_404(self.d, "baselines", baseline_id, p.tenant_id, "baseline")
        if b["status"] != "proposed":
            raise Conflict(f"only a proposed baseline can be approved (this one is {b['status']})", code="not_proposed")
        if b["proposed_by"] == p.id and self._other_approvers(p) > 0:
            raise Forbidden("a different member must approve this baseline (segregation of duties)", code="segregation_of_duties")
        for other in self.d.db.find("baselines", tenant_id=p.tenant_id, where={
                "project_id": b["project_id"], "profile_id": b["profile_id"], "status": "approved"}, limit=50):
            other["status"], other["retired_at"] = "retired", iso(self.d.now())
            self.d.db.put("baselines", other, tenant_id=p.tenant_id)
        b.update({"status": "approved", "approved_by": p.id, "approved_by_name": p.actor, "approved_at": iso(self.d.now()),
                  "self_approved": b["proposed_by"] == p.id})
        self.d.db.put("baselines", b, tenant_id=p.tenant_id)
        audit(self.d, p, "baseline.approved", baseline_id, {"self_approved": b["self_approved"]})
        return {k: v for k, v in b.items() if k != "stats"}

    def _other_approvers(self, p: Principal) -> int:
        from ...domain.governance.authorization import ROLE_PERMISSIONS, Role
        n = 0
        for m in self.d.db.find("memberships", tenant_id=p.tenant_id, limit=1000):
            if m["user_id"] != p.id and Permission.BASELINES_APPROVE in ROLE_PERMISSIONS[Role(m["role"])]:
                n += 1
        return n

    def retire(self, p: Principal, baseline_id: str) -> dict[str, Any]:
        p.require(Permission.BASELINES_APPROVE)
        b = get_or_404(self.d, "baselines", baseline_id, p.tenant_id, "baseline")
        b.update({"status": "retired", "retired_at": iso(self.d.now())})
        self.d.db.put("baselines", b, tenant_id=p.tenant_id)
        audit(self.d, p, "baseline.retired", baseline_id)
        return {k: v for k, v in b.items() if k != "stats"}


class AlertService:
    def __init__(self, deps: Any) -> None:
        self.d = deps

    def raise_alert(self, tenant_id: str, project_id: str, kind: str, dedupe_key: str, title: str, detail: str,
                    severity: str, run_id: str = "") -> dict[str, Any]:
        """Deduplicated: a repeat within the open window increments a counter instead of spamming the console."""
        now = iso(self.d.now())
        key = f"{tenant_id}:{dedupe_key}"
        existing = self.d.db.get_by_ukey("alerts", key)
        if existing and not existing.get("acknowledged_at"):
            existing["count"] = int(existing.get("count", 1)) + 1
            existing["last_seen_at"] = now
            existing["run_id"] = run_id or existing.get("run_id", "")
            self.d.db.put("alerts", existing, tenant_id=tenant_id)
            return existing
        rec = {"id": new_id("alr"), "tenant_id": tenant_id, "project_id": project_id, "kind": kind, "dedupe_key": dedupe_key,
               "title": title[:200], "detail": detail[:1000], "severity": severity, "created_at": now, "count": 1,
               "last_seen_at": now, "run_id": run_id, "acknowledged_by": "", "acknowledged_at": None}
        if existing:                                                   # acknowledged earlier: a new occurrence is a new alert
            self.d.db.delete("alerts", existing["id"], tenant_id=tenant_id)
        self.d.db.insert("alerts", rec, tenant_id=tenant_id, ukey=key)
        return rec

    def list(self, p: Principal, open_only: bool = True, limit: Any = 100, offset: Any = 0) -> list[dict[str, Any]]:
        p.require(Permission.ALERTS_READ)
        lim, off = clean_page(limit, offset)
        where = {"acknowledged_at": None} if open_only else None
        return [a for a in self.d.db.find("alerts", tenant_id=p.tenant_id, where=where, order_by="last_seen_at", limit=lim, offset=off)
                if not a.get("project_id") or p.can_project(a["project_id"])]

    def acknowledge(self, p: Principal, alert_id: str, note: str = "") -> dict[str, Any]:
        p.require(Permission.ALERTS_ACK)
        a = get_or_404(self.d, "alerts", alert_id, p.tenant_id, "alert")
        a.update({"acknowledged_by": p.actor, "acknowledged_at": iso(self.d.now()), "note": note})
        self.d.db.put("alerts", a, tenant_id=p.tenant_id)
        audit(self.d, p, "alert.acknowledged", alert_id)
        return a


class AuditQueries:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    def list(self, p: Principal, limit: Any = 100, offset: Any = 0, action: str = "") -> list[dict[str, Any]]:
        p.require(Permission.AUDIT_READ)
        lim, off = clean_page(limit, offset, max_limit=500, default=100)
        return self.d.db.audit_events(p.tenant_id, limit=lim, offset=off, action_prefix=action)

    def verify(self, p: Principal) -> dict[str, Any]:
        p.require(Permission.AUDIT_READ)
        return self.d.db.verify_audit(p.tenant_id)

    def export_csv(self, p: Principal) -> str:
        p.require(Permission.AUDIT_EXPORT)
        self.plans.require_feature(p.tenant_id, F_AUDIT_EXPORT, "Audit export")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["seq_hash", "prev_hash", "at", "actor", "actor_kind", "action", "target", "correlation_id", "data"])
        import json
        for ev in self.d.db.audit_events(p.tenant_id, limit=10000, desc=False):
            w.writerow([csv_safe(ev.get("hash")), csv_safe(ev.get("prev_hash")), csv_safe(ev.get("at")), csv_safe(ev.get("actor")),
                        csv_safe(ev.get("actor_kind")), csv_safe(ev.get("action")), csv_safe(ev.get("target")),
                        csv_safe(ev.get("correlation_id")), csv_safe(json.dumps(ev.get("data", {}), sort_keys=True))])
        audit(self.d, p, "audit.exported", p.tenant_id)
        return buf.getvalue()


class ScheduleService:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    def list(self, p: Principal) -> list[dict[str, Any]]:
        p.require(Permission.RUNS_READ)
        return [s for s in self.d.db.find("schedules", tenant_id=p.tenant_id, order_by="created_at", desc=False, limit=500)
                if p.can_project(s["project_id"])]

    def create(self, p: Principal, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.SCHEDULES_MANAGE)
        self.plans.require_feature(p.tenant_id, F_SCHEDULES, "Scheduled runs")
        p.require_project(data["project_id"])
        get_or_404(self.d, "projects", data["project_id"], p.tenant_id, "project")
        self.d.configs.resolve(p.tenant_id, "profile", data["profile_id"])
        if data.get("policy_id"):
            self.d.configs.resolve(p.tenant_id, "policy", data["policy_id"])
        self._validate_url(data["source_url"])
        now = self.d.now()
        rec = {"id": new_id("sch"), "tenant_id": p.tenant_id, "project_id": data["project_id"], "name": data["name"],
               "interval_minutes": data["interval_minutes"], "source_url": data["source_url"], "profile_id": data["profile_id"],
               "policy_id": data.get("policy_id") or "standard", "destination_id": data.get("destination_id", ""),
               "created_by": p.actor, "created_at": iso(now), "next_run_at": iso(now + timedelta(minutes=data["interval_minutes"])),
               "enabled": True, "last_run_at": None, "last_run_id": "", "last_error": ""}
        self.d.db.insert("schedules", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "schedule.created", rec["id"], {"every_min": rec["interval_minutes"]})
        return rec

    def _validate_url(self, url: str) -> None:
        try:
            self.d.webhooks.validate_target(url)          # same SSRF guard as webhooks
        except Exception as exc:                          # noqa: BLE001
            raise ValidationFailed(f"the source URL was rejected: {exc}", details={"fields": {"source_url": str(exc)[:200]}}) from exc

    def update(self, p: Principal, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.SCHEDULES_MANAGE)
        rec = get_or_404(self.d, "schedules", sid, p.tenant_id, "schedule")
        p.require_project(rec["project_id"])
        if data.get("source_url"):
            self._validate_url(data["source_url"])
        for k in ("name", "interval_minutes", "source_url", "profile_id", "policy_id", "destination_id", "enabled"):
            if data.get(k) is not None and data.get(k) != "":
                rec[k] = data[k]
        if "interval_minutes" in data and data["interval_minutes"]:
            rec["next_run_at"] = iso(self.d.now() + timedelta(minutes=rec["interval_minutes"]))
        self.d.db.put("schedules", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "schedule.updated", sid)
        return rec

    def delete(self, p: Principal, sid: str) -> None:
        p.require(Permission.SCHEDULES_MANAGE)
        if not self.d.db.delete("schedules", sid, tenant_id=p.tenant_id):
            raise NotFound("schedule not found")
        audit(self.d, p, "schedule.deleted", sid)
