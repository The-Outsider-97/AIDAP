"""Billing, schedules, retention, contact and dashboard queries."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from ...domain.accounts.models import SubscriptionStatus
from ...domain.accounts.plans import PLAN_ORDER
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import Conflict, Forbidden, NotFound, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id, parse_iso
from ..context import Principal, system_principal
from ..utils.common import audit, audit_system, clean_page, get_or_404, sanitize_doc

__all__ = ["BillingService", "ScheduleRunner", "RetentionService", "ContactService", "DashboardQueries"]

_SELF_SERVE = ("starter", "team", "business")
_STRIPE_STATUS = {"active": SubscriptionStatus.ACTIVE, "trialing": SubscriptionStatus.TRIALING,
                  "past_due": SubscriptionStatus.PAST_DUE, "unpaid": SubscriptionStatus.PAST_DUE,
                  "canceled": SubscriptionStatus.CANCELLED, "incomplete_expired": SubscriptionStatus.EXPIRED}


def _ts(v: Any) -> str | None:
    if v in (None, ""):
        return None
    return iso(datetime.fromtimestamp(int(v), tz=timezone.utc))


class BillingService:
    def __init__(self, deps: Any, plans: Any, notify: Any, alerts: Any) -> None:
        self.d, self.plans, self.notify, self.alerts = deps, plans, notify, alerts

    # ------------------------------------------------------------------ reads
    def catalog(self) -> dict[str, Any]:
        order = [self.d.plans[i].to_dict() for i in PLAN_ORDER if i in self.d.plans]
        return {"plans": order, "currency": "EUR", "vat": "Prices exclude VAT.", "provider": self.d.billing.provider,
                "sandbox": self.d.billing.provider == "sandbox",
                "note": "Prices and allowances are launch hypotheses and may change before general availability.",
                "contact": self.d.settings.business_email}

    def state(self, p: Principal) -> dict[str, Any]:
        p.require(Permission.USAGE_READ)
        sub = self.plans.subscription(p.tenant_id)
        eff = self.plans.effective_plan_id(sub)
        return {"subscription": {k: v for k, v in sub.items() if k not in ("provider_customer_id", "provider_subscription_id")},
                "plan": self.d.plans[sub["plan_id"]].to_dict(), "effective_plan": self.d.plans[eff].to_dict(),
                "provider": self.d.billing.provider, "sandbox": self.d.billing.provider == "sandbox",
                "can_manage": p.can(Permission.BILLING_MANAGE), "manual": sub.get("provider") == "manual"}

    # ------------------------------------------------------------------ actions
    def _customer(self, p: Principal, sub: dict[str, Any]) -> str:
        if not sub.get("provider_customer_id"):
            t = self.d.db.get("tenants", p.tenant_id, tenant_id=p.tenant_id) or {}
            sub["provider_customer_id"] = self.d.billing.create_customer(p.tenant_id, t.get("billing_email", p.email), t.get("name", ""))
            sub["provider"] = self.d.billing.provider
            self.d.db.put("subscriptions", sub, tenant_id=p.tenant_id)
        return sub["provider_customer_id"]

    def checkout(self, p: Principal, plan_id: str) -> dict[str, Any]:
        p.require(Permission.BILLING_MANAGE)
        if plan_id == "enterprise":
            raise ValidationFailed("Enterprise is arranged with sales - use the contact form", details={"fields": {"plan_id": "contact_sales"}})
        if plan_id not in _SELF_SERVE:
            raise ValidationFailed("choose Starter, Team or Business", details={"fields": {"plan_id": "invalid"}})
        sub = self.plans.subscription(p.tenant_id)
        if sub.get("provider") == "manual":
            raise Conflict("this account is on a manually managed plan; contact support to change it", code="manual_plan")
        cust = self._customer(p, sub)
        base = self.d.settings.base_url.rstrip("/")
        day = self.d.now().strftime("%Y%m%d")
        res = self.d.billing.create_checkout(tenant_id=p.tenant_id, customer_id=cust, plan_id=plan_id,
                                             success_url=f"{base}/app/billing?checkout=success",
                                             cancel_url=f"{base}/app/billing?checkout=cancelled",
                                             idempotency_key=f"{p.tenant_id}:{plan_id}:{day}")
        self.d.db.put("billing_sessions", {"id": res["id"], "tenant_id": p.tenant_id, "kind": "plan", "plan_id": plan_id,
                                           "created_at": iso(self.d.now()), "completed": False}, tenant_id=p.tenant_id)
        audit(self.d, p, "billing.checkout_started", p.tenant_id, {"plan": plan_id, "provider": self.d.billing.provider})
        return {"id": res["id"], "url": res["url"], "sandbox": bool(res.get("sandbox"))}

    def topup(self, p: Principal, amount_cents: int) -> dict[str, Any]:
        p.require(Permission.BILLING_MANAGE)
        sub = self.plans.subscription(p.tenant_id)
        if self.plans.effective_plan_id(sub) in ("developer",):
            raise Forbidden("managed-inference top-ups need a paid plan", code="feature_not_in_plan")
        cust = self._customer(p, sub)
        base = self.d.settings.base_url.rstrip("/")
        res = self.d.billing.create_topup(tenant_id=p.tenant_id, customer_id=cust, amount_cents=amount_cents,
                                          success_url=f"{base}/app/billing?topup=success", cancel_url=f"{base}/app/billing?topup=cancelled",
                                          idempotency_key=f"{p.tenant_id}:topup:{amount_cents}:{new_id('k')}")
        self.d.db.put("billing_sessions", {"id": res["id"], "tenant_id": p.tenant_id, "kind": "topup", "amount_cents": amount_cents,
                                           "created_at": iso(self.d.now()), "completed": False}, tenant_id=p.tenant_id)
        audit(self.d, p, "billing.topup_started", p.tenant_id, {"cents": amount_cents})
        return {"id": res["id"], "url": res["url"], "sandbox": bool(res.get("sandbox"))}

    def portal(self, p: Principal) -> dict[str, Any]:
        p.require(Permission.BILLING_MANAGE)
        sub = self.plans.subscription(p.tenant_id)
        if sub.get("provider") not in ("stripe", "sandbox"):
            raise Conflict("there is no billing account to manage yet", code="no_billing_account")
        return {"url": self.d.billing.create_portal(sub["provider_customer_id"], f"{self.d.settings.base_url.rstrip('/')}/app/billing")}

    def cancel(self, p: Principal) -> dict[str, Any]:
        p.require(Permission.BILLING_MANAGE)
        sub = self.plans.subscription(p.tenant_id)
        if sub["plan_id"] == "developer":
            raise Conflict("the free plan has nothing to cancel", code="nothing_to_cancel")
        if sub.get("provider") == "manual":
            raise Conflict("this plan is managed by agreement; contact support", code="manual_plan")
        if sub.get("provider_subscription_id"):
            self.d.billing.cancel_subscription(sub["provider_subscription_id"], at_period_end=True)
        sub.update({"cancel_at_period_end": True})
        self.d.db.put("subscriptions", sub, tenant_id=p.tenant_id)
        audit(self.d, p, "billing.cancel_requested", p.tenant_id)
        return self.state(p)

    def settings(self, p: Principal, data: dict[str, Any]) -> dict[str, Any]:
        p.require(Permission.BILLING_MANAGE)
        sub = self.plans.subscription(p.tenant_id)
        for k in ("auto_overage", "hold_on_exhaustion"):
            if k in data and data[k] is not None:
                sub[k] = bool(data[k])
        self.d.db.put("subscriptions", sub, tenant_id=p.tenant_id)
        audit(self.d, p, "billing.settings_changed", p.tenant_id, {k: sub[k] for k in ("auto_overage", "hold_on_exhaustion")})
        return self.state(p)

    def sandbox_complete(self, p: Principal, session_id: str) -> dict[str, Any]:
        """Stands in for the provider's success callback. Exists only for the sandbox provider, never in production."""
        p.require(Permission.BILLING_MANAGE)
        if self.d.billing.provider != "sandbox" or self.d.settings.production:
            raise Forbidden("the billing sandbox is not available here", code="sandbox_disabled")
        s = get_or_404(self.d, "billing_sessions", session_id, p.tenant_id, "checkout session")
        if s["completed"]:
            return self.state(p)
        event = ({"id": "evt_sbx_" + session_id, "type": "checkout_completed", "tenant_id": p.tenant_id, "plan_id": s["plan_id"],
                  "customer_id": self.plans.subscription(p.tenant_id).get("provider_customer_id", ""),
                  "subscription_id": self.d.billing.new_subscription_id(), "session_id": session_id}
                 if s["kind"] == "plan" else
                 {"id": "evt_sbx_" + session_id, "type": "topup_completed", "tenant_id": p.tenant_id,
                  "amount_cents": s["amount_cents"], "session_id": session_id})
        self.apply_event(event)
        s["completed"] = True
        self.d.db.put("billing_sessions", s, tenant_id=p.tenant_id)
        return self.state(p)

    # ------------------------------------------------------------------ provider events
    def handle_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        event = self.d.billing.parse_webhook(payload, signature)       # verifies the signature or raises
        return self.apply_event(event)

    def _tenant_for(self, event: dict[str, Any]) -> str:
        if event.get("tenant_id") and self.d.db.get("tenants", event["tenant_id"], tenant_id=event["tenant_id"]):
            return event["tenant_id"]
        for key, field in (("customer_id", "provider_customer_id"), ("subscription_id", "provider_subscription_id")):
            if event.get(key):
                found = self.d.db.find("subscriptions", where={field: event[key]}, limit=1)
                if found:
                    return found[0]["tenant_id"]
        return ""

    def apply_event(self, event: dict[str, Any]) -> dict[str, Any]:
        eid, etype = event.get("id", ""), event.get("type", "ignored")
        if etype == "ignored" or not eid:
            return {"handled": False, "type": etype}
        if not self.d.db.insert("billing_events", {"id": eid, "type": etype, "created_at": iso(self.d.now())}, ukey=f"evt:{eid}"):
            return {"handled": True, "duplicate": True, "type": etype}          # providers retry; handling is idempotent
        tenant = self._tenant_for(event)
        if not tenant:
            return {"handled": False, "type": etype, "reason": "unknown tenant"}
        sub = self.plans.subscription(tenant)
        now = self.d.now()
        if etype == "checkout_completed":
            plan = event.get("plan_id") or ""
            if plan not in _SELF_SERVE:
                return {"handled": False, "type": etype, "reason": "unknown plan"}
            sub.update({"plan_id": plan, "status": "active", "provider": self.d.billing.provider,
                        "provider_customer_id": event.get("customer_id") or sub.get("provider_customer_id", ""),
                        "provider_subscription_id": event.get("subscription_id") or sub.get("provider_subscription_id", ""),
                        "current_period_start": iso(now), "current_period_end": iso(now + timedelta(days=30)),
                        "cancel_at_period_end": False, "past_due_since": None})
        elif etype == "subscription_updated":
            st = _STRIPE_STATUS.get(event.get("status", ""), SubscriptionStatus.ACTIVE)
            if event.get("plan_id") in _SELF_SERVE:
                sub["plan_id"] = event["plan_id"]
            sub.update({"status": st.value, "cancel_at_period_end": bool(event.get("cancel_at_period_end")),
                        "provider_customer_id": event.get("customer_id") or sub.get("provider_customer_id", ""),
                        "provider_subscription_id": event.get("subscription_id") or sub.get("provider_subscription_id", "")})
            if _ts(event.get("period_end")):
                sub["current_period_end"], sub["current_period_start"] = _ts(event["period_end"]), _ts(event.get("period_start")) or sub.get("current_period_start")
            if st == SubscriptionStatus.PAST_DUE and not sub.get("past_due_since"):
                sub["past_due_since"] = iso(now)
        elif etype == "subscription_cancelled":
            sub.update({"status": SubscriptionStatus.CANCELLED.value, "cancel_at_period_end": True})
            if _ts(event.get("period_end")):
                sub["current_period_end"] = _ts(event["period_end"])
        elif etype == "payment_failed":
            sub.update({"status": SubscriptionStatus.PAST_DUE.value})
            sub["past_due_since"] = sub.get("past_due_since") or iso(now)
            t = self.d.db.get("tenants", tenant, tenant_id=tenant) or {}
            if t.get("billing_email"):
                self.notify.email(tenant, t["billing_email"], "AIDAP: payment failed",
                                  "We could not collect your latest payment. Your plan stays active for "
                                  f"{self.d.settings.past_due_grace_days} days; update your payment method in Billing to keep it.",
                                  dedupe_key=f"payfail:{eid}")
            self.alerts.raise_alert(tenant, "", "billing", "billing:past_due", "Payment failed",
                                    "Update your payment method before the grace period ends.", "high")
        elif etype == "payment_succeeded":
            sub.update({"status": SubscriptionStatus.ACTIVE.value, "past_due_since": None})
        elif etype == "topup_completed":
            sub["topup_inference_cents"] = int(sub.get("topup_inference_cents", 0)) + int(event.get("amount_cents") or 0)
        else:
            return {"handled": False, "type": etype}
        self.d.db.put("subscriptions", sub, tenant_id=tenant)
        audit_system(self.d, tenant, f"billing.{etype}", tenant, {"plan": sub.get("plan_id"), "status": sub.get("status")})
        return {"handled": True, "type": etype, "tenant_id": tenant}

    # ------------------------------------------------------------------ operator
    def admin_set_plan(self, tenant_id: str, plan_id: str, *, days: int = 365, note: str = "", actor: str = "operator") -> dict[str, Any]:
        """Enterprise (and any manually agreed plan) is set by an operator, never self-served."""
        if plan_id not in self.d.plans:
            raise ValidationFailed(f"unknown plan {plan_id!r}")
        if not self.d.db.get("tenants", tenant_id, tenant_id=tenant_id):
            raise NotFound("tenant not found")
        sub = self.plans.subscription(tenant_id)
        now = self.d.now()
        sub.update({"plan_id": plan_id, "status": "active", "provider": "manual" if plan_id != "developer" else "none",
                    "current_period_start": iso(now), "current_period_end": iso(now + timedelta(days=days)) if plan_id != "enterprise" else None,
                    "cancel_at_period_end": False, "past_due_since": None, "note": note})
        self.d.db.put("subscriptions", sub, tenant_id=tenant_id)
        audit_system(self.d, tenant_id, "billing.plan_set_by_operator", tenant_id, {"plan": plan_id, "note": note[:200]}, actor=actor)
        return sub


class ScheduleRunner:
    """Fetches each due source through the SSRF-safe fetcher and submits it as an ordinary run."""

    def __init__(self, deps: Any, plans: Any, runs: Any, alerts: Any) -> None:
        self.d, self.plans, self.runs, self.alerts = deps, plans, runs, alerts

    def tick(self, limit: int = 20) -> int:
        from ...domain.accounts.plans import F_SCHEDULES
        now, n = self.d.now(), 0
        due = self.d.db.find("schedules", where={"enabled": True, "next_run_at": ("<=", iso(now))}, order_by="next_run_at",
                             desc=False, limit=limit)
        for s in due:
            tenant = s["tenant_id"]
            s["next_run_at"] = iso(now + timedelta(minutes=int(s["interval_minutes"])))
            s["last_run_at"] = iso(now)
            try:
                if not self.plans.plan_for(tenant).has(F_SCHEDULES):
                    raise Conflict("scheduled runs are not included in the current plan", code="feature_not_in_plan")
                fetched = self.d.fetcher.fetch(s["source_url"], max_bytes=self.d.settings.max_upload_bytes)
                digest = hashlib.sha256(fetched.data).hexdigest()
                if s.get("last_digest") == digest:
                    s["last_error"] = ""
                    s["last_note"] = "unchanged since the previous fetch; no run created"
                else:
                    run = self.runs.submit(system_principal(tenant, f"schedule:{s['name']}"), project_id=s["project_id"],
                                           data=fetched.data, filename=fetched.filename or s["name"], media_type=fetched.media_type,
                                           profile_id=s["profile_id"], policy_id=s["policy_id"], destination_id=s.get("destination_id", ""),
                                           source_class="third_party", label=f"scheduled: {s['name']}", source="schedule",
                                           asset_name=s["name"], idempotency_key=f"sch:{s['id']}:{digest[:16]}",
                                           metadata={"source_url": s["source_url"], "etag": fetched.etag, "source_revision": fetched.etag or digest[:12]})
                    s.update({"last_run_id": run["id"], "last_digest": digest, "last_error": "", "last_note": ""})
                    n += 1
            except Exception as exc:                                    # noqa: BLE001
                msg = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
                s["last_error"] = str(msg)[:300]
                self.alerts.raise_alert(tenant, s["project_id"], "schedule_failed", f"schedule:{s['id']}", "A scheduled run failed",
                                        f"{s['name']}: {s['last_error']}", "medium")
            self.d.db.put("schedules", s, tenant_id=tenant)
        return n


class RetentionService:
    """Evidence and inputs are kept for the plan's retention period, then purged; the audit log is never purged."""

    def __init__(self, deps: Any, plans: Any) -> None:
        self.d, self.plans = deps, plans

    def sweep(self, limit: int = 500) -> int:
        now, n = self.d.now(), 0
        cache: dict[str, int] = {}
        for run in self.d.db.find("runs", where={"state": ["completed", "failed", "cancelled"], "expired": None},
                                  order_by="created_at", desc=False, limit=limit):
            tenant = run["tenant_id"]
            days = cache.setdefault(tenant, self.plans.retention_days(tenant))
            finished = parse_iso(run.get("finished_at") or run["created_at"])
            if finished is None or finished + timedelta(days=days) > now:
                continue
            if self.d.db.count("reviews", tenant_id=tenant, where={"run_id": run["id"], "state": "open"}):
                continue
            q = self.d.db.get_by_ukey("quarantine", f"{tenant}:{run['id']}")
            if q and q["state"] == "held":
                continue
            self._purge(run, tenant)
            audit_system(self.d, tenant, "retention.purged", run["id"], {"retention_days": days})
            n += 1
        return n

    def _purge(self, run: dict[str, Any], tenant: str) -> None:
        """Remove the content-bearing records of one run. The decision, reasons and audit trail stay: they are the record."""
        ver = self.d.db.get("versions", run["version_id"], tenant_id=tenant)
        siblings = self.d.db.count("runs", tenant_id=tenant, where={"version_id": run["version_id"], "expired": None})
        if ver and not ver.get("purged") and siblings <= 1:
            try:
                self.d.blobs.delete(ver["blob_ref"])
            except Exception:                                       # noqa: BLE001
                pass
            ver["purged"] = True
            self.d.db.put("versions", ver, tenant_id=tenant)
        ev = self.d.db.get("evidence", run["id"], tenant_id=tenant)
        if ev:
            try:
                self.d.blobs.delete(ev["blob_ref"])
            except Exception:                                       # noqa: BLE001
                pass
            self.d.db.delete("evidence", run["id"], tenant_id=tenant)
        self.d.db.delete("run_artifacts", run["id"], tenant_id=tenant)
        try:
            self.d.checkpoints.drop(run["id"])
        except Exception:                                           # noqa: BLE001
            pass
        run["expired"] = True
        self.d.db.put("runs", run, tenant_id=tenant)

    # ------------------------------------------------------------------ customer-initiated deletion and export
    def delete_run_content(self, p: Principal, run_id: str) -> dict[str, Any]:
        """Delete the stored input, results and evidence bundle of a finished run before the retention window ends."""
        p.require(Permission.RETENTION_MANAGE)
        run = get_or_404(self.d, "runs", run_id, p.tenant_id, "run")
        if run["state"] not in ("completed", "failed", "cancelled"):
            raise Conflict("the run is still in progress", code="run_not_finished")
        if run.get("expired"):
            return {"run_id": run_id, "deleted": True, "already": True}
        if self.d.db.count("reviews", tenant_id=p.tenant_id, where={"run_id": run_id, "state": "open"}):
            raise Conflict("an open review needs this content; resolve it first", code="review_open")
        q = self.d.db.get_by_ukey("quarantine", f"{p.tenant_id}:{run_id}")
        if q and q["state"] == "held":
            raise Conflict("the artifact is held in quarantine; dispose of it first", code="quarantine_held")
        self._purge(run, p.tenant_id)
        run["expired"] = True
        run["content_deleted_by"] = p.actor
        self.d.db.put("runs", run, tenant_id=p.tenant_id)
        audit(self.d, p, "run.content_deleted", run_id, {"requested": True})
        return {"run_id": run_id, "deleted": True, "already": False}

    EXPORT_COLLECTIONS = ("projects", "runs", "decisions", "reviews", "grants", "destinations", "configs", "baselines",
                          "schedules", "alerts", "deliveries", "memberships", "usage", "quarantine", "assets",
                          "finding_feedback", "suites", "suite_cases", "suite_runs")

    def export_tenant(self, p: Principal) -> dict[str, Any]:
        """A machine-readable copy of the organisation's records. Stored content and credentials are not included."""
        p.require(Permission.TENANT_DELETE)               # owner only: this is the whole organisation's data
        out: dict[str, Any] = {"schema": "aidap.export/1", "generated_at": iso(self.d.now()), "tenant_id": p.tenant_id,
                               "note": "Records only. Uploaded content, evidence bundles and credentials are not included."}
        t = self.d.db.get("tenants", p.tenant_id)
        out["organization"] = sanitize_doc(t) if t else {}
        for coll in self.EXPORT_COLLECTIONS:
            rows = self.d.db.find(coll, tenant_id=p.tenant_id, order_by="created_at", desc=False, limit=5000)
            out[coll] = [sanitize_doc(r) for r in rows]
        out["audit"] = self.d.db.audit_events(p.tenant_id, limit=5000, desc=False)
        audit(self.d, p, "tenant.exported", p.tenant_id, {"collections": len(self.EXPORT_COLLECTIONS)})
        return out


class ContactService:
    def __init__(self, deps: Any, notify: Any) -> None:
        self.d, self.notify = deps, notify

    def submit(self, data: dict[str, Any], ip: str = "") -> dict[str, Any]:
        if data.get("website"):                                       # honeypot: humans never fill it; say "ok", store nothing
            return {"received": True}
        rec = {"id": new_id("msg"), "created_at": iso(self.d.now()), "name": data["name"], "email": data["email"],
               "company": data.get("company", ""), "topic": data.get("topic", "enterprise"), "message": data["message"],
               "ip_hash": hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else ""}
        self.d.db.insert("contact_messages", rec)
        body = (f"Topic: {rec['topic']}\nFrom: {rec['name']} <{rec['email']}>\nCompany: {rec['company'] or '-'}\n\n{rec['message']}\n")
        # Delivered only to the business inbox - never to the (unverified) sender address.
        self.notify.email("", self.d.settings.business_email, f"[AIDAP {rec['topic']}] {rec['name']}", body,
                          reply_to=rec["email"], dedupe_key=f"contact:{rec['id']}")
        return {"received": True, "id": rec["id"]}


class DashboardQueries:
    def __init__(self, deps: Any, usage: Any) -> None:
        self.d, self.usage = deps, usage

    def overview(self, p: Principal, project_id: str = "") -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        t = p.tenant_id
        base = {"project_id": project_id} if project_id else {}
        runs = [r for r in self.d.db.find("runs", tenant_id=t, where=base or None, limit=500) if p.can_project(r["project_id"])]
        by_dec: dict[str, int] = {}
        for r in runs:
            by_dec[r.get("decision") or r["state"]] = by_dec.get(r.get("decision") or r["state"], 0) + 1
        since = iso(self.d.now() - timedelta(days=14))
        series: dict[str, dict[str, int]] = {}
        for r in runs:
            if r["created_at"] >= since:
                day = r["created_at"][:10]
                series.setdefault(day, {})
                key = r.get("decision") or "pending"
                series[day][key] = series[day].get(key, 0) + 1
        codes: dict[str, int] = {}
        for r in runs[:60]:
            art = self.d.db.get("run_artifacts", r["id"], tenant_id=t)
            for res in ((art or {}).get("results") or {}).values():
                for f in res["findings"]:
                    codes[f["code"]] = codes.get(f["code"], 0) + 1
        return {
            "runs_total": self.d.db.count("runs", tenant_id=t, where=base or None), "by_decision": by_dec,
            "series": [{"day": d, **v} for d, v in sorted(series.items())],
            "top_findings": [{"code": c, "count": n} for c, n in sorted(codes.items(), key=lambda x: -x[1])[:8]],
            "open_reviews": self.d.db.count("reviews", tenant_id=t, where={"state": "open"}),
            "held_quarantine": self.d.db.count("quarantine", tenant_id=t, where={"state": "held"}),
            "open_alerts": self.d.db.count("alerts", tenant_id=t, where={"acknowledged_at": None}),
            "recent": [{k: r.get(k) for k in ("id", "filename", "label", "decision", "state", "created_at", "project_id")} for r in runs[:8]],
            "usage": self.usage.summary(p) if p.can(Permission.USAGE_READ) else None,
        }
