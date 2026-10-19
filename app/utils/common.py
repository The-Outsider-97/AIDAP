"""Small helpers shared by services."""

from __future__ import annotations

from typing import Any

from ...domain.reports.models import AuditEvent
from ...domain.utils.domain_helpers import iso, new_id
from ..context import Principal

__all__ = ["audit", "audit_system", "clean_page", "get_or_404", "sanitize_doc"]


def audit(deps: Any, p: Principal, action: str, target: str = "", data: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = AuditEvent(new_id("aud"), p.tenant_id, p.actor, p.kind, action, target, deps.now(), p.correlation_id,
                    _bounded(data or {}))
    return deps.db.append_audit(p.tenant_id, ev.to_dict())


def audit_system(deps: Any, tenant_id: str, action: str, target: str = "", data: dict[str, Any] | None = None,
                 actor: str = "system") -> dict[str, Any]:
    ev = AuditEvent(new_id("aud"), tenant_id, actor, "system", action, target, deps.now(), "", _bounded(data or {}))
    return deps.db.append_audit(tenant_id, ev.to_dict())


def _bounded(data: dict[str, Any], limit: int = 4000) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = v[:500]
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [x if isinstance(x, (int, float, bool)) else str(x)[:200] for x in list(v)[:50]]
        elif isinstance(v, dict):
            out[k] = {str(a)[:80]: (b if isinstance(b, (int, float, bool)) or b is None else str(b)[:200])
                      for a, b in list(v.items())[:30]}
        else:
            out[k] = str(v)[:200]
    return out


def clean_page(limit: Any, offset: Any, *, max_limit: int = 200, default: int = 50) -> tuple[int, int]:
    try:
        lim = int(limit) if limit not in (None, "") else default
        off = int(offset) if offset not in (None, "") else 0
    except (TypeError, ValueError):
        lim, off = default, 0
    return max(1, min(lim, max_limit)), max(0, off)


def get_or_404(deps: Any, coll: str, doc_id: str, tenant_id: str, what: str = "record") -> dict[str, Any]:
    from ...domain.utils.domain_errors import NotFound
    doc = deps.db.get(coll, doc_id, tenant_id=tenant_id)
    if doc is None:
        raise NotFound(f"{what} not found", code=f"{coll}_not_found")
    return doc


_SECRET_KEYS = {"password_hash", "password_salt", "mfa_secret_sealed", "recovery_hashes", "digest", "csrf_digest",
                "secret_ref", "secret_sealed"}


def sanitize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Remove credential material from any record before it leaves the app layer."""
    return {k: v for k, v in doc.items() if k not in _SECRET_KEYS}
