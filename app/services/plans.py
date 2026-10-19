"""Entitlements and metering. The plan a tenant *effectively* has is derived from its subscription's state."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...domain.accounts.models import SubscriptionStatus
from ...domain.accounts.plans import PLAN_ORDER, Plan
from ...domain.accounts.usage import (METER_CPU_MS, METER_INFERENCE_CENTS, METER_RUN, METER_SCAN_BYTES, billable_bytes)
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import FeatureNotInPlan, NotFound, PayloadTooLarge, QuotaExceeded
from ...domain.utils.domain_helpers import iso, parse_iso, period_key
from ..context import Principal

__all__ = ["PlanService", "UsageService"]


class PlanService:
    def __init__(self, deps: Any) -> None:
        self.d = deps

    # ------------------------------------------------------------------ subscription
    def subscription(self, tenant_id: str) -> dict[str, Any]:
        sub = self.d.db.get("subscriptions", tenant_id, tenant_id=tenant_id)
        if sub is None:
            sub = {"id": tenant_id, "tenant_id": tenant_id, "plan_id": "developer", "status": SubscriptionStatus.ACTIVE.value,
                   "provider": "none", "created_at": iso(self.d.now()), "current_period_start": iso(self.d.now()),
                   "current_period_end": None, "cancel_at_period_end": False, "provider_customer_id": "",
                   "provider_subscription_id": "", "past_due_since": None, "pending_plan_id": "",
                   "topup_inference_cents": 0, "auto_overage": self.d.settings.auto_overage, "hold_on_exhaustion": True}
            self.d.db.insert("subscriptions", sub, tenant_id=tenant_id)
        return sub

    def effective_plan_id(self, sub: dict[str, Any]) -> str:
        now = self.d.now()
        status, plan = sub.get("status"), sub.get("plan_id", "developer")
        end = parse_iso(sub.get("current_period_end"))
        if status in (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIALING.value):
            if plan == "enterprise" or end is None or now <= end + timedelta(days=2):
                return plan
            return "developer" if sub.get("provider") != "none" else plan   # lapsed paid period never grants entitlements
        if status == SubscriptionStatus.CANCELLED.value:
            return plan if end is not None and now <= end else "developer"
        if status == SubscriptionStatus.PAST_DUE.value:
            since = parse_iso(sub.get("past_due_since")) or now
            return plan if now <= since + timedelta(days=self.d.settings.past_due_grace_days) else "developer"
        return "developer"

    def plan_for(self, tenant_id: str) -> Plan:
        return self.d.plans[self.effective_plan_id(self.subscription(tenant_id))]

    def require_feature(self, tenant_id: str, feature: str, label: str = "") -> Plan:
        plan = self.plan_for(tenant_id)
        if not plan.has(feature):
            raise FeatureNotInPlan(f"{label or feature} is not included in the {plan.name} plan",
                                   details={"feature": feature, "plan": plan.id,
                                            "available_from": next((pid for pid in PLAN_ORDER
                                                                    if self.d.plans[pid].has(feature)), None)})
        return plan

    def enforce_project_limit(self, tenant_id: str) -> None:
        plan = self.plan_for(tenant_id)
        n = self.d.db.count("projects", tenant_id=tenant_id, where={"archived": False})
        if n >= plan.max_projects:
            raise QuotaExceeded(f"the {plan.name} plan allows {plan.max_projects} project(s)",
                                details={"limit": "projects", "plan": plan.id, "max": plan.max_projects})

    def enforce_seat_limit(self, tenant_id: str, extra: int = 1) -> None:
        plan = self.plan_for(tenant_id)
        members = self.d.db.count("memberships", tenant_id=tenant_id)
        pending = self.d.db.count("invitations", tenant_id=tenant_id, where={"accepted_at": None})
        if members + pending + extra > plan.seats:
            raise QuotaExceeded(f"the {plan.name} plan includes {plan.seats} seat(s)",
                                details={"limit": "seats", "plan": plan.id, "max": plan.seats})

    def retention_days(self, tenant_id: str) -> int:
        from ...domain.accounts.plans import F_CONFIG_RETENTION
        plan = self.plan_for(tenant_id)
        t = self.d.db.get("tenants", tenant_id, tenant_id=tenant_id) or {}
        custom = t.get("retention_days")
        if custom and plan.has(F_CONFIG_RETENTION):
            return min(int(custom), plan.evidence_retention_days)
        return plan.evidence_retention_days


class UsageService:
    def __init__(self, deps: Any, plans: PlanService) -> None:
        self.d, self.plans = deps, plans

    def _totals_id(self, tenant: str, period: str) -> str:
        return f"{tenant}:{period}"

    def totals(self, tenant_id: str, period: str | None = None) -> dict[str, Any]:
        period = period or period_key(self.d.now())
        doc = self.d.db.get("usage_totals", self._totals_id(tenant_id, period), tenant_id=tenant_id)
        return doc or {"id": self._totals_id(tenant_id, period), "tenant_id": tenant_id, "period": period,
                       "runs": 0, "scan_bytes": 0, "inference_cents": 0, "cpu_ms": 0}

    def record(self, tenant_id: str, run_id: str, project_id: str, meter: str, quantity: int, note: str = "") -> bool:
        """Idempotent per (run, meter): a replayed or retried stage can never charge twice."""
        if quantity <= 0 and meter != METER_RUN:
            return False
        now = self.d.now()
        period = period_key(now)
        entry = {"id": f"{run_id}:{meter}", "tenant_id": tenant_id, "period": period, "meter": meter,
                 "quantity": int(quantity), "recorded_at": iso(now), "created_at": iso(now), "run_id": run_id,
                 "project_id": project_id, "note": note}
        with self.d.db.transaction():
            if not self.d.db.insert("usage", entry, tenant_id=tenant_id, ukey=entry["id"]):
                return False
            tot = self.totals(tenant_id, period)
            key = {METER_RUN: "runs", METER_SCAN_BYTES: "scan_bytes", METER_INFERENCE_CENTS: "inference_cents",
                   METER_CPU_MS: "cpu_ms"}[meter]
            tot[key] = int(tot.get(key, 0)) + int(quantity)
            tot["created_at"] = tot.get("created_at") or iso(now)
            self.d.db.put("usage_totals", tot, tenant_id=tenant_id)
        return True

    # ------------------------------------------------------------------ admission control
    def admit(self, tenant_id: str, size_bytes: int) -> dict[str, Any]:
        plan = self.plans.plan_for(tenant_id)
        sub = self.plans.subscription(tenant_id)
        if size_bytes > plan.max_run_bytes:
            raise PayloadTooLarge(f"the {plan.name} plan accepts inputs up to {plan.max_run_bytes // 1_000_000} MB",
                                  details={"limit": "max_run_mb", "plan": plan.id})
        tot = self.totals(tenant_id)
        overage = bool(sub.get("auto_overage"))
        warnings: list[str] = []
        if tot["runs"] >= plan.included_runs:
            if not overage:
                raise QuotaExceeded(f"the {plan.name} plan's {plan.included_runs:,} runs for {tot['period']} are used; "
                                    "upgrade or enable overage (new work is held, nothing is silently dropped)",
                                    details={"limit": "runs", "plan": plan.id, "used": tot["runs"],
                                             "included": plan.included_runs})
            warnings.append("run allowance exceeded: overage applies")
        if tot["scan_bytes"] + billable_bytes(size_bytes) > plan.included_scan_bytes:
            if not overage:
                raise QuotaExceeded(f"the {plan.name} plan's scan allowance for {tot['period']} is used",
                                    details={"limit": "scan_gb", "plan": plan.id, "used": tot["scan_bytes"],
                                             "included": plan.included_scan_bytes})
            warnings.append("scan allowance exceeded: overage applies")
        return {"plan": plan.id, "warnings": warnings, "runs_used": tot["runs"], "runs_included": plan.included_runs}

    def inference_left_cents(self, tenant_id: str) -> int:
        plan = self.plans.plan_for(tenant_id)
        sub = self.plans.subscription(tenant_id)
        used = self.totals(tenant_id)["inference_cents"]
        return int(plan.inference_allowance_cents + int(sub.get("topup_inference_cents", 0)) - used)

    def summary(self, p: Principal, period: str | None = None) -> dict[str, Any]:
        p.require(Permission.USAGE_READ)
        plan = self.plans.plan_for(p.tenant_id)
        sub = self.plans.subscription(p.tenant_id)
        tot = self.totals(p.tenant_id, period)
        projects = self.d.db.count("projects", tenant_id=p.tenant_id, where={"archived": False})
        seats = self.d.db.count("memberships", tenant_id=p.tenant_id)

        def ratio(used: float, cap: float) -> float | None:
            return None if not cap else round(used / cap, 4)
        return {"period": tot["period"], "plan": plan.to_dict(),
                "subscription": {k: sub.get(k) for k in ("status", "provider", "current_period_end", "cancel_at_period_end",
                                                         "auto_overage", "hold_on_exhaustion", "pending_plan_id")},
                "used": {"runs": tot["runs"], "scan_bytes": tot["scan_bytes"], "scan_gb": round(tot["scan_bytes"] / 1e9, 6),
                         "inference_cents": tot["inference_cents"], "cpu_ms": tot["cpu_ms"], "projects": projects, "seats": seats},
                "limits": {"runs": plan.included_runs, "scan_bytes": plan.included_scan_bytes,
                           "inference_cents": plan.inference_allowance_cents + int(sub.get("topup_inference_cents", 0)),
                           "projects": plan.max_projects, "seats": plan.seats},
                "ratios": {"runs": ratio(tot["runs"], plan.included_runs),
                           "scan": ratio(tot["scan_bytes"], plan.included_scan_bytes),
                           "inference": ratio(tot["inference_cents"], plan.inference_allowance_cents
                                              + int(sub.get("topup_inference_cents", 0))),
                           "projects": ratio(projects, plan.max_projects), "seats": ratio(seats, plan.seats)},
                "overage_enabled": bool(sub.get("auto_overage"))}

    def history(self, p: Principal, months: int = 6) -> list[dict[str, Any]]:
        p.require(Permission.USAGE_READ)
        docs = self.d.db.find("usage_totals", tenant_id=p.tenant_id, order_by="period", limit=max(1, min(months, 36)))
        return [{k: d[k] for k in ("period", "runs", "scan_bytes", "inference_cents", "cpu_ms")} for d in docs]
