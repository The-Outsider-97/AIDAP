"""Who is acting, and what they may do. Authorization is enforced here, in the app layer - never only in the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.governance.authorization import Permission, ROLE_PERMISSIONS, Role, SCOPE_PERMISSIONS
from ..domain.utils.domain_errors import Forbidden

__all__ = ["Principal", "system_principal"]


@dataclass(frozen=True)
class Principal:
    kind: str                                   # user | api_key | system
    id: str
    tenant_id: str
    permissions: frozenset[Permission]
    role: str = ""
    email: str = ""
    name: str = ""
    project_ids: tuple[str, ...] = ()           # empty = every project in the tenant
    session_id: str = ""
    key_id: str = ""
    correlation_id: str = ""
    ip: str = ""

    @property
    def actor(self) -> str:
        return self.email or self.id

    def can(self, perm: Permission) -> bool:
        return perm in self.permissions

    def require(self, perm: Permission) -> None:
        if perm not in self.permissions:
            raise Forbidden(f"your role does not permit '{perm.value}'", code="forbidden",
                            details={"required": perm.value})

    def can_project(self, project_id: str) -> bool:
        return not self.project_ids or project_id in self.project_ids

    def require_project(self, project_id: str) -> None:
        if not self.can_project(project_id):
            raise Forbidden("you do not have access to this project", code="project_forbidden")

    @classmethod
    def for_user(cls, *, user_id: str, email: str, name: str, tenant_id: str, role: str, project_ids: list[str],
                 session_id: str = "", ip: str = "", correlation_id: str = "") -> "Principal":
        perms = ROLE_PERMISSIONS[Role(role)]
        return cls("user", user_id, tenant_id, frozenset(perms), role, email, name, tuple(project_ids), session_id,
                   "", correlation_id, ip)

    @classmethod
    def for_api_key(cls, *, key_id: str, name: str, tenant_id: str, scopes: list[str], project_ids: list[str],
                    ip: str = "", correlation_id: str = "") -> "Principal":
        perms: set[Permission] = set()
        for s in scopes:
            perms |= SCOPE_PERMISSIONS.get(s, frozenset())
        return cls("api_key", key_id, tenant_id, frozenset(perms), "api_key", "", name, tuple(project_ids), "", key_id,
                   correlation_id, ip)


def system_principal(tenant_id: str, label: str = "system") -> Principal:
    return Principal("system", label, tenant_id, frozenset(Permission), "system", label, label)
