"""Roles, permissions and API-key scopes. Enforced server-side by the app layer."""

from __future__ import annotations

from enum import Enum

__all__ = ["Role", "Permission", "ROLE_PERMISSIONS", "SCOPE_PERMISSIONS", "ROLE_RANK", "role_at_least"]


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    SECURITY = "security"
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(str, Enum):
    RUNS_SUBMIT = "runs.submit"
    RUNS_READ = "runs.read"
    RUNS_MANAGE = "runs.manage"            # cancel / retry / rerun / redact
    FINDINGS_READ = "findings.read"
    EVIDENCE_READ = "evidence.read"
    REVIEWS_READ = "reviews.read"
    REVIEWS_RESOLVE = "reviews.resolve"
    QUARANTINE_ACCESS = "quarantine.access"     # distinct from ordinary review permission
    QUARANTINE_DISPOSE = "quarantine.dispose"
    POLICIES_READ = "policies.read"
    POLICIES_WRITE = "policies.write"
    POLICIES_PUBLISH = "policies.publish"
    BASELINES_PROPOSE = "baselines.propose"
    BASELINES_APPROVE = "baselines.approve"
    DESTINATIONS_MANAGE = "destinations.manage"
    WEBHOOKS_MANAGE = "webhooks.manage"
    APIKEYS_MANAGE = "apikeys.manage"
    MEMBERS_MANAGE = "members.manage"
    BILLING_MANAGE = "billing.manage"
    USAGE_READ = "usage.read"
    AUDIT_READ = "audit.read"
    AUDIT_EXPORT = "audit.export"
    SCHEDULES_MANAGE = "schedules.manage"
    ALERTS_READ = "alerts.read"
    ALERTS_ACK = "alerts.ack"
    RETENTION_MANAGE = "retention.manage"
    PROJECTS_MANAGE = "projects.manage"
    TENANT_DELETE = "tenant.delete"
    DELIVERIES_READ = "deliveries.read"


P = Permission

_VIEW = {P.RUNS_READ, P.FINDINGS_READ, P.EVIDENCE_READ, P.REVIEWS_READ, P.POLICIES_READ, P.USAGE_READ,
         P.ALERTS_READ, P.DELIVERIES_READ}
_ANALYST = _VIEW | {P.RUNS_SUBMIT, P.RUNS_MANAGE, P.POLICIES_WRITE, P.BASELINES_PROPOSE, P.ALERTS_ACK}
_REVIEWER = _VIEW | {P.REVIEWS_RESOLVE, P.ALERTS_ACK, P.RUNS_SUBMIT}
_SECURITY = _REVIEWER | {P.QUARANTINE_ACCESS, P.QUARANTINE_DISPOSE, P.AUDIT_READ, P.BASELINES_APPROVE}
_ADMIN = (_ANALYST | _REVIEWER | _SECURITY |
          {P.POLICIES_PUBLISH, P.DESTINATIONS_MANAGE, P.WEBHOOKS_MANAGE, P.APIKEYS_MANAGE, P.MEMBERS_MANAGE,
           P.AUDIT_EXPORT, P.SCHEDULES_MANAGE, P.RETENTION_MANAGE, P.PROJECTS_MANAGE})
_OWNER = _ADMIN | {P.BILLING_MANAGE, P.TENANT_DELETE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(_VIEW),
    Role.ANALYST: frozenset(_ANALYST),
    Role.REVIEWER: frozenset(_REVIEWER),
    Role.SECURITY: frozenset(_SECURITY),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_OWNER),
}

ROLE_RANK = {Role.VIEWER: 0, Role.ANALYST: 1, Role.REVIEWER: 2, Role.SECURITY: 3, Role.ADMIN: 4, Role.OWNER: 5}


def role_at_least(role: Role | str, minimum: Role | str) -> bool:
    return ROLE_RANK[Role(role)] >= ROLE_RANK[Role(minimum)]


# API keys are scoped narrowly: a pipeline key cannot read billing or approve anything.
SCOPE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "runs:write": frozenset({P.RUNS_SUBMIT, P.RUNS_READ, P.FINDINGS_READ}),
    "runs:read": frozenset({P.RUNS_READ, P.FINDINGS_READ, P.EVIDENCE_READ}),
    "deliveries:read": frozenset({P.DELIVERIES_READ, P.RUNS_READ}),
    "policies:read": frozenset({P.POLICIES_READ}),
    "usage:read": frozenset({P.USAGE_READ}),
}
