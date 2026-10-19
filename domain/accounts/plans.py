"""Plans and entitlements (whitepaper Tables 15/16).

Figures are the whitepaper's *pricing hypotheses*, exposed as configuration:
``configs/plans.yaml`` may override them without code changes. Entitlements
are published only when implemented; every feature flag below has an
enforcement point in the app layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Plan", "DEFAULT_PLANS", "PLAN_ORDER", "F_API", "F_WEBHOOKS", "F_REVIEW_ROLES", "F_SCHEDULES",
           "F_OBJECT_STORE", "F_AUDIT_EXPORT", "F_CONFIG_RETENTION", "F_MODEL_ASSIST", "F_CUSTOM_POLICY",
           "F_PRIORITY_SUPPORT", "F_SSO", "F_PRIVATE_DEPLOYMENT", "FEATURE_LABELS", "plan_from_dict"]

F_API = "api"
F_WEBHOOKS = "webhooks"
F_REVIEW_ROLES = "review_roles"
F_SCHEDULES = "schedules"
F_OBJECT_STORE = "object_store"
F_AUDIT_EXPORT = "audit_export"
F_CONFIG_RETENTION = "configurable_retention"
F_MODEL_ASSIST = "model_assist"
F_CUSTOM_POLICY = "custom_policy"
F_PRIORITY_SUPPORT = "priority_support"
F_SSO = "sso"
F_PRIVATE_DEPLOYMENT = "private_deployment"

FEATURE_LABELS = {
    F_API: "API and Python SDK",
    F_WEBHOOKS: "Signed webhooks",
    F_REVIEW_ROLES: "Reviewer and security roles",
    F_SCHEDULES: "Scheduled runs",
    F_OBJECT_STORE: "Object-store delivery",
    F_AUDIT_EXPORT: "Audit export",
    F_CONFIG_RETENTION: "Configurable retention",
    F_MODEL_ASSIST: "Managed model-assisted checks",
    F_CUSTOM_POLICY: "Custom profiles and policies",
    F_PRIORITY_SUPPORT: "Priority business-hours support",
    F_SSO: "Supported SSO integration",
    F_PRIVATE_DEPLOYMENT: "Private deployment",
}


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    tagline: str
    price_month_cents: int | None          # EUR cents, excl. VAT; None = contact sales
    included_runs: int
    included_scan_bytes: int               # decoded bytes examined (1 GB = 10**9)
    inference_allowance_cents: int
    max_projects: int
    evidence_retention_days: int
    max_run_bytes: int
    seats: int
    features: frozenset[str] = field(default_factory=frozenset)
    support: str = "community"
    contact_sales: bool = False
    annual_hint: str = ""
    onboarding_hint: str = ""
    highlights: tuple[str, ...] = ()
    currency: str = "EUR"

    def has(self, feature: str) -> bool:
        return feature in self.features

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "tagline": self.tagline, "price_month_cents": self.price_month_cents,
            "currency": self.currency, "included_runs": self.included_runs,
            "included_scan_gb": self.included_scan_bytes / 1e9,
            "inference_allowance_cents": self.inference_allowance_cents, "max_projects": self.max_projects,
            "evidence_retention_days": self.evidence_retention_days, "max_run_mb": self.max_run_bytes / 1e6,
            "seats": self.seats, "features": sorted(self.features), "support": self.support,
            "contact_sales": self.contact_sales, "annual_hint": self.annual_hint,
            "onboarding_hint": self.onboarding_hint, "highlights": list(self.highlights),
        }


_BASE = frozenset({F_API})
_STARTER = _BASE | {F_MODEL_ASSIST, F_CUSTOM_POLICY}
_TEAM = _STARTER | {F_WEBHOOKS, F_REVIEW_ROLES, F_SCHEDULES, F_OBJECT_STORE}
_BUSINESS = _TEAM | {F_AUDIT_EXPORT, F_CONFIG_RETENTION, F_PRIORITY_SUPPORT}
_ENTERPRISE = _BUSINESS | {F_SSO, F_PRIVATE_DEPLOYMENT}

GB = 10 ** 9
MB = 10 ** 6

DEFAULT_PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("developer", "Developer", "Local SDK, examples and a hosted sandbox for synthetic data.", 0,
         100, GB // 10, 0, 1, 7, 10 * MB, 1, _BASE, "community",
         highlights=("100 runs / month", "0.1 GB scan allowance", "7-day evidence retention",
                     "Built-in profile templates", "Community support")),
    Plan("starter", "Starter", "One production ingestion path with a managed-inference allowance.", 3900,
         1000, 5 * GB, 300, 1, 30, 25 * MB, 3, _STARTER, "self-service",
         highlights=("1 project", "1,000 runs / month", "5 GB deterministic scans", "€3 managed-inference allowance",
                     "30-day evidence retention", "Custom profiles and policies")),
    Plan("team", "Team", "Shared review workflow, schedules and webhooks.", 14900,
         10000, 50 * GB, 1500, 5, 90, 50 * MB, 15, _TEAM, "email",
         highlights=("5 projects", "10,000 runs / month", "50 GB deterministic scans",
                     "€15 managed-inference allowance", "90-day evidence retention",
                     "Review roles, schedules and webhooks", "Object-store delivery")),
    Plan("business", "Business", "Longer retention, audit export and priority support.", 49900,
         50000, 250 * GB, 5000, 20, 365, 100 * MB, 60, _BUSINESS, "priority business hours",
         highlights=("20 projects", "50,000 runs / month", "250 GB deterministic scans",
                     "€50 managed-inference allowance", "One-year evidence, configurable retention",
                     "Audit export", "Priority business-hours support")),
    Plan("enterprise", "Enterprise", "Private deployment, SSO integration, contractual support.", None,
         10 ** 9, 10 ** 5 * GB, 0, 10 ** 6, 1095, 500 * MB, 10 ** 6, _ENTERPRISE, "contractual",
         contact_sales=True, annual_hint="From €12,000–30,000 / year, subject to scope",
         onboarding_hint="Separate €3,000–8,000 onboarding hypothesis",
         highlights=("Private deployment", "Supported SSO integration", "Contractual support",
                     "Security review", "Infrastructure priced separately")),
)}

PLAN_ORDER = ["developer", "starter", "team", "business", "enterprise"]


def plan_from_dict(base: Plan, d: dict[str, Any]) -> Plan:
    """Apply a ``plans.yaml`` override to a default plan."""
    from dataclasses import replace
    kw: dict[str, Any] = {}
    mapping = {"price_month_cents": int, "included_runs": int, "inference_allowance_cents": int,
               "max_projects": int, "evidence_retention_days": int, "seats": int, "support": str,
               "tagline": str, "annual_hint": str, "onboarding_hint": str}
    for key, cast in mapping.items():
        if key in d and d[key] is not None:
            kw[key] = cast(d[key])
    if "included_scan_gb" in d:
        kw["included_scan_bytes"] = int(float(d["included_scan_gb"]) * GB)
    if "max_run_mb" in d:
        kw["max_run_bytes"] = int(float(d["max_run_mb"]) * MB)
    if "features" in d:
        kw["features"] = frozenset(d["features"])
    if "highlights" in d:
        kw["highlights"] = tuple(d["highlights"])
    return replace(base, **kw)
