"""Delivery (stage 20). Webhook notices go out for every outcome (metadata only); the artifact itself is released only
when the *current* decision still authorises it - re-verified at send time, never at planning time."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...contracts.versions import WEBHOOK_SCHEMA
from ...domain.accounts.plans import F_OBJECT_STORE, F_WEBHOOKS
from ...domain.data.classification import DeliveryKind
from ...domain.decisions import FitnessDecision
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import AIDAPError, Conflict, IntegrityViolation
from ...domain.utils.domain_helpers import iso, new_id, sha256_hex
from ..context import Principal
from ..utils.common import audit, audit_system, clean_page, get_or_404

__all__ = ["DeliveryService", "DeliveryRetry"]


class DeliveryRetry(Exception):
    """Raised for a transient failure; the worker re-queues with backoff."""


class DeliveryService:
    def __init__(self, deps: Any, plans: Any, alerts: Any) -> None:
        self.d, self.plans, self.alerts = deps, plans, alerts

    # ------------------------------------------------------------------ planning (called when a decision is issued)
    def plan(self, run: dict[str, Any], decision: FitnessDecision, dest: dict[str, Any] | None, version: dict[str, Any]) -> list[dict[str, Any]]:
        if decision.shadow or dest is None or not dest.get("enabled", True):
            return []
        kind = dest["delivery"]
        authorized = decision.release_authorized(self.d.now(), version["content_digest"])
        out: list[dict[str, Any]] = []
        if kind == DeliveryKind.WEBHOOK.value:
            out.append(self._create(run, decision, dest, "webhook"))
        elif kind == DeliveryKind.OBJECT_STORE.value and authorized:
            out.append(self._create(run, decision, dest, "object_store"))
        elif kind == DeliveryKind.PULL.value:
            out.append(self._create(run, decision, dest, "pull", state="available" if authorized else "withheld",
                                    note="" if authorized else f"decision is {decision.decision.value}"))
        for rec in out:
            if rec["state"] == "pending":
                self.d.queue.enqueue("delivery", {"delivery_id": rec["id"], "tenant_id": rec["tenant_id"]},
                                     dedupe_key=f"delivery:{rec['id']}", max_attempts=self.d.settings.max_attempts)
        return out

    def _create(self, run: dict[str, Any], decision: FitnessDecision, dest: dict[str, Any], kind: str, *,
                state: str = "pending", note: str = "") -> dict[str, Any]:
        rid = new_id("dlv")
        rec = {"id": rid, "tenant_id": run["tenant_id"], "project_id": run["project_id"], "run_id": run["id"],
               "decision_id": decision.id, "destination_id": dest["id"], "kind": kind, "state": state, "attempts": 0,
               "event_id": new_id("evt"), "created_at": iso(self.d.now()), "last_error": "", "note": note,
               "sent_at": None, "decision": decision.decision.value}
        key = f"{run['tenant_id']}:{decision.id}:{dest['id']}:{kind}"
        if not self.d.db.insert("deliveries", rec, tenant_id=run["tenant_id"], ukey=key):
            return self.d.db.get_by_ukey("deliveries", key) or rec
        return rec

    # ------------------------------------------------------------------ sending (worker)
    def payload(self, run: dict[str, Any], decision: FitnessDecision, rec: dict[str, Any], authorized: bool) -> dict[str, Any]:
        """Metadata only: never content, never previews, never finding excerpts."""
        body = {
            "schema": WEBHOOK_SCHEMA, "event_id": rec["event_id"], "type": "decision.issued", "created_at": iso(self.d.now()),
            "run_id": run["id"], "project_id": run["project_id"], "decision_id": decision.id,
            "decision": decision.decision.value, "status": decision.status.value, "disposition": decision.disposition.value,
            "release_authorized": authorized, "reason_codes": sorted({r.code for r in decision.reasons}),
            "policy": decision.policy_ref, "profile": decision.profile_ref, "input_digest": decision.input_digest,
            "released_digest": decision.released_digest, "expires_at": iso(decision.expires_at), "shadow": decision.shadow,
            "links": {"run": f"{self.d.settings.base_url}/runs/{run['id']}"},
        }
        if authorized:
            body["links"]["artifact"] = f"{self.d.settings.base_url}/api/v1/runs/{run['id']}/artifact"
        return body

    def process(self, delivery_id: str) -> str:
        rec = self.d.db.get("deliveries", delivery_id)
        if rec is None or rec["state"] in ("sent", "failed", "withheld", "available"):
            return rec["state"] if rec else "missing"
        tenant = rec["tenant_id"]
        run = self.d.db.get("runs", rec["run_id"], tenant_id=tenant)
        dest = self.d.db.get("destinations", rec["destination_id"], tenant_id=tenant)
        if run is None or dest is None or not dest.get("enabled", True):
            return self._finish(rec, "failed", "destination or run no longer exists / is disabled")
        # Re-verify at send time: the CURRENT decision of the run decides, not the one that planned this delivery.
        decision = FitnessDecision.from_dict(self.d.db.get("decisions", run["decision_id"], tenant_id=tenant))
        version = self.d.db.get("versions", run["version_id"], tenant_id=tenant) or {}
        authorized = decision.release_authorized(self.d.now(), version.get("content_digest"))
        plan = self.plans.plan_for(tenant)
        rec["attempts"] += 1
        try:
            if rec["kind"] == "webhook":
                if not plan.has(F_WEBHOOKS):
                    return self._finish(rec, "failed", "webhooks are not included in the current plan")
                secret = self.d.box.open(dest["secret_sealed"], aad=dest["id"].encode()).decode() if dest.get("secret_sealed") else ""
                res = self.d.webhooks.send(dest["target_url"], secret, rec["event_id"], self.payload(run, decision, rec, authorized))
                if res.ok:
                    return self._finish(rec, "sent", "")
                if res.retryable and rec["attempts"] < self.d.settings.max_attempts:
                    rec["last_error"] = (res.error or f"HTTP {res.status}")[:300]
                    self.d.db.put("deliveries", rec, tenant_id=tenant)
                    raise DeliveryRetry(rec["last_error"])
                return self._finish(rec, "failed", (res.error or f"HTTP {res.status}")[:300], alert=True)
            if rec["kind"] == "object_store":
                if not plan.has(F_OBJECT_STORE):
                    return self._finish(rec, "failed", "object-store delivery is not included in the current plan")
                if not authorized:
                    return self._finish(rec, "withheld", f"release is no longer authorised (decision {decision.decision.value})")
                data = self.d.blobs.get(version["blob_ref"])
                if "sha256:" + sha256_hex(data) != decision.released_digest:
                    raise IntegrityViolation("artifact digest changed since the decision", code="digest_mismatch_at_send")
                key = f"{dest['target_url'].strip('/')}/{run['id']}/{(version.get('filename') or 'artifact').split('/')[-1]}"
                self.d.objects.deliver(key, data, content_type=version.get("media_type") or "application/octet-stream")
                return self._finish(rec, "sent", "")
        except DeliveryRetry:
            raise
        except IntegrityViolation as exc:
            return self._finish(rec, "failed", exc.message, alert=True)
        except AIDAPError as exc:
            return self._finish(rec, "failed", exc.message, alert=True)
        except Exception as exc:                                       # noqa: BLE001
            rec["last_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            if rec["attempts"] >= self.d.settings.max_attempts:
                return self._finish(rec, "failed", rec["last_error"], alert=True)
            self.d.db.put("deliveries", rec, tenant_id=tenant)
            raise DeliveryRetry(rec["last_error"]) from exc
        return self._finish(rec, "failed", f"unknown delivery kind {rec['kind']}")

    def _finish(self, rec: dict[str, Any], state: str, error: str, *, alert: bool = False) -> str:
        rec["state"], rec["last_error"] = state, error
        if state == "sent":
            rec["sent_at"] = iso(self.d.now())
        self.d.db.put("deliveries", rec, tenant_id=rec["tenant_id"])
        audit_system(self.d, rec["tenant_id"], f"delivery.{state}", rec["id"], {"run": rec["run_id"], "kind": rec["kind"],
                                                                                "error": error[:200]})
        if alert and state == "failed":
            self.alerts.raise_alert(rec["tenant_id"], rec["project_id"], "delivery_failed", f"delivery:{rec['destination_id']}",
                                    "A delivery failed", f"{rec['kind']} delivery for run {rec['run_id']} failed: {error[:200]}",
                                    "medium", rec["run_id"])
        return state

    # ------------------------------------------------------------------ queries / actions
    def list(self, p: Principal, run_id: str = "", state: str = "", limit: Any = None, offset: Any = None) -> list[dict[str, Any]]:
        p.require(Permission.DELIVERIES_READ)
        lim, off = clean_page(limit, offset)
        where = {k: v for k, v in (("run_id", run_id), ("state", state)) if v}
        return [x for x in self.d.db.find("deliveries", tenant_id=p.tenant_id, where=where or None, limit=lim, offset=off)
                if p.can_project(x["project_id"])]

    def retry(self, p: Principal, delivery_id: str) -> dict[str, Any]:
        p.require(Permission.DESTINATIONS_MANAGE)
        rec = get_or_404(self.d, "deliveries", delivery_id, p.tenant_id, "delivery")
        if rec["state"] != "failed":
            raise Conflict("only a failed delivery can be retried", code="not_failed")
        rec.update({"state": "pending", "attempts": 0, "last_error": ""})
        self.d.db.put("deliveries", rec, tenant_id=p.tenant_id)
        self.d.queue.enqueue("delivery", {"delivery_id": rec["id"], "tenant_id": p.tenant_id},
                             dedupe_key=f"delivery:{rec['id']}:{new_id('r')}", max_attempts=self.d.settings.max_attempts)
        audit(self.d, p, "delivery.retried", delivery_id)
        return rec

    def record_pull(self, p: Principal, run: dict[str, Any], decision: FitnessDecision) -> None:
        audit(self.d, p, "artifact.pulled", run["id"], {"decision": decision.id, "digest": decision.released_digest[:24]})
        self.d.db.insert("deliveries", {"id": new_id("dlv"), "tenant_id": p.tenant_id, "project_id": run["project_id"],
                                        "run_id": run["id"], "decision_id": decision.id, "destination_id": run.get("destination_id") or "",
                                        "kind": "pull", "state": "sent", "attempts": 1, "event_id": new_id("evt"),
                                        "created_at": iso(self.d.now()), "last_error": "", "note": f"pulled by {p.actor}",
                                        "sent_at": iso(self.d.now()), "decision": decision.decision.value}, tenant_id=p.tenant_id)
