"""Built-in templates (profiles, policies, plans) and tenant-owned versioned configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ...domain.accounts.plans import DEFAULT_PLANS, F_CUSTOM_POLICY, PLAN_ORDER, Plan, plan_from_dict
from ...domain.governance.authorization import Permission
from ...domain.policies import AssurancePolicy, IntendedUseProfile
from ...domain.policies.versions import blocking, lint
from ...domain.utils.domain_errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..context import Principal
from ..utils.common import audit

__all__ = ["TemplateCatalog", "ConfigService", "load_plans"]

KINDS = ("profile", "policy")


def load_plans(configs_dir: Path) -> dict[str, Plan]:
    plans = dict(DEFAULT_PLANS)
    f = configs_dir / "plans.yaml"
    if f.exists():
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for pid, override in (data.get("plans") or {}).items():
            if pid in plans and isinstance(override, dict):
                plans[pid] = plan_from_dict(plans[pid], override)
    return plans


class TemplateCatalog:
    """Read-only, shipped with the product. Every tenant sees these; they are version 1 and always published."""

    def __init__(self, configs_dir: Path) -> None:
        self.profiles: dict[str, tuple[IntendedUseProfile, dict[str, Any]]] = {}
        self.policies: dict[str, tuple[AssurancePolicy, dict[str, Any]]] = {}
        for f in sorted((configs_dir / "profiles").glob("*.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            p = IntendedUseProfile.from_dict(doc)
            self.profiles[p.id] = (p, doc)
        for f in sorted((configs_dir / "policies").glob("*.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            q = AssurancePolicy.from_dict(doc)
            self.policies[q.id] = (q, doc)
        for p, _ in self.profiles.values():
            bad = blocking(lint(profile=p))
            if bad:
                raise ValueError(f"built-in profile {p.id} fails lint: {bad[0].message}")
        for q, _ in self.policies.values():
            bad = blocking(lint(policy=q))
            if bad:
                raise ValueError(f"built-in policy {q.id} fails lint: {bad[0].message}")

    def get(self, kind: str, cid: str) -> tuple[Any, dict[str, Any]] | None:
        return (self.profiles if kind == "profile" else self.policies).get(cid)

    def summaries(self, kind: str) -> list[dict[str, Any]]:
        src = self.profiles if kind == "profile" else self.policies
        return [{"id": cid, "name": obj.name, "description": getattr(obj, "description", ""), "builtin": True,
                 "version": 1, "published_version": 1, "draft_version": None, "task": getattr(obj, "task", ""),
                 "mode": getattr(obj, "mode", None)} for cid, (obj, _) in src.items()]


class ConfigService:
    def __init__(self, deps: Any, plans: Any) -> None:
        self.d = deps
        self.plans = plans

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _doc_id(tenant: str, kind: str, cid: str, version: int) -> str:
        return f"{tenant}:{kind}:{cid}:{version}"

    def _versions(self, tenant: str, kind: str, cid: str) -> list[dict[str, Any]]:
        return self.d.db.find("configs", tenant_id=tenant, where={"kind": kind, "config_id": cid}, order_by="version",
                              limit=500)

    def _parse(self, kind: str, doc: dict[str, Any], cid: str) -> Any:
        doc = {**doc, "id": cid}
        try:
            return IntendedUseProfile.from_dict(doc) if kind == "profile" else AssurancePolicy.from_dict(doc)
        except ValidationFailed:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ValidationFailed(f"{kind} document is malformed: {exc}") from exc

    def lint_documents(self, profile: dict | None, policy: dict | None) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        prof = pol = None
        if profile:
            prof = self._parse("profile", profile, str(profile.get("id") or "draft"))
        if policy:
            pol = self._parse("policy", policy, str(policy.get("id") or "draft"))
        issues = [i.to_dict() for i in lint(prof, pol)]
        return {"issues": issues, "errors": sum(1 for i in issues if i["level"] == "error"),
                "warnings": sum(1 for i in issues if i["level"] == "warning"), "publishable": not any(
                    i["level"] == "error" for i in issues)}

    # ------------------------------------------------------------------ listing / reading
    def list(self, p: Principal, kind: str) -> list[dict[str, Any]]:
        p.require(Permission.POLICIES_READ)
        out = self.d.catalog.summaries(kind)
        by_id: dict[str, list[dict[str, Any]]] = {}
        for v in self.d.db.find("configs", tenant_id=p.tenant_id, where={"kind": kind}, order_by="version", limit=5000):
            by_id.setdefault(v["config_id"], []).append(v)
        for cid, versions in by_id.items():
            pub = [v for v in versions if v["status"] == "published"]
            draft = [v for v in versions if v["status"] == "draft"]
            out.append({"id": cid, "name": versions[-1]["name"], "builtin": False,
                        "description": versions[-1]["document"].get("description", ""),
                        "published_version": pub[-1]["version"] if pub else None,
                        "draft_version": draft[-1]["version"] if draft else None, "version": versions[-1]["version"],
                        "task": versions[-1]["document"].get("task", ""), "mode": versions[-1]["document"].get("mode"),
                        "updated_at": versions[-1].get("published_at") or versions[-1]["created_at"]})
        return out

    def get(self, p: Principal, kind: str, cid: str) -> dict[str, Any]:
        p.require(Permission.POLICIES_READ)
        builtin = self.d.catalog.get(kind, cid)
        versions = self._versions(p.tenant_id, kind, cid)
        if builtin and not versions:
            obj, doc = builtin
            return {"id": cid, "name": obj.name, "builtin": True, "kind": kind,
                    "versions": [{"version": 1, "status": "published", "document": doc, "note": "built-in template"}]}
        if not versions:
            raise NotFound(f"{kind} '{cid}' not found", code="config_not_found")
        return {"id": cid, "name": versions[-1]["name"], "builtin": False, "kind": kind,
                "versions": [{k: v[k] for k in ("version", "status", "document", "note", "created_by", "created_at",
                                                "published_by", "published_at", "lint") if k in v} for v in versions]}

    # ------------------------------------------------------------------ authoring
    def _require_custom(self, p: Principal) -> None:
        self.plans.require_feature(p.tenant_id, F_CUSTOM_POLICY, "custom profiles and policies")

    def create(self, p: Principal, kind: str, cid: str, name: str, document: dict[str, Any], note: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_WRITE)
        self._require_custom(p)
        if self.d.catalog.get(kind, cid) is not None:
            raise Conflict(f"'{cid}' is a built-in {kind}; choose another id", code="id_reserved")
        if self._versions(p.tenant_id, kind, cid):
            raise Conflict(f"{kind} '{cid}' already exists; add a new version instead", code="config_exists")
        return self._add_version(p, kind, cid, name, document, note, 1)

    def add_version(self, p: Principal, kind: str, cid: str, document: dict[str, Any], note: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_WRITE)
        self._require_custom(p)
        versions = self._versions(p.tenant_id, kind, cid)
        if not versions:
            raise NotFound(f"{kind} '{cid}' not found", code="config_not_found")
        if any(v["status"] == "draft" for v in versions):
            raise Conflict("a draft already exists; edit or publish it first", code="draft_exists")
        return self._add_version(p, kind, cid, versions[-1]["name"], document, note, versions[-1]["version"] + 1)

    def update_draft(self, p: Principal, kind: str, cid: str, document: dict[str, Any], note: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_WRITE)
        drafts = [v for v in self._versions(p.tenant_id, kind, cid) if v["status"] == "draft"]
        if not drafts:
            raise NotFound("there is no draft to edit", code="draft_not_found")
        d = drafts[-1]
        obj = self._parse(kind, document, cid)
        d["document"] = {**document, "id": cid}
        d["note"] = note or d.get("note", "")
        d["lint"] = [i.to_dict() for i in lint(obj if kind == "profile" else None, obj if kind == "policy" else None)]
        d["created_by"] = p.actor
        self.d.db.put("configs", d, tenant_id=p.tenant_id)
        audit(self.d, p, f"{kind}.draft_updated", f"{cid}@{d['version']}")
        return d

    def _add_version(self, p: Principal, kind: str, cid: str, name: str, document: dict[str, Any], note: str,
                     version: int) -> dict[str, Any]:
        document = {**document, "id": cid}
        obj = self._parse(kind, document, cid)
        issues = [i.to_dict() for i in lint(obj if kind == "profile" else None, obj if kind == "policy" else None)]
        rec = {"id": self._doc_id(p.tenant_id, kind, cid, version), "tenant_id": p.tenant_id, "kind": kind,
               "config_id": cid, "version": version, "status": "draft", "name": name or cid, "document": document,
               "note": note, "created_by": p.actor, "created_by_id": p.id, "created_at": self.d.now().isoformat(),
               "lint": issues}
        self.d.db.put("configs", rec, tenant_id=p.tenant_id)
        audit(self.d, p, f"{kind}.version_created", f"{cid}@{version}", {"errors": sum(1 for i in issues if i['level'] == 'error')})
        return rec

    def publish(self, p: Principal, kind: str, cid: str, version: int) -> dict[str, Any]:
        p.require(Permission.POLICIES_PUBLISH)
        rec = self.d.db.get("configs", self._doc_id(p.tenant_id, kind, cid, version), tenant_id=p.tenant_id)
        if rec is None:
            raise NotFound("version not found", code="config_not_found")
        if rec["status"] != "draft":
            raise Conflict(f"only a draft can be published (this one is {rec['status']})", code="not_a_draft")
        obj = self._parse(kind, rec["document"], cid)
        errors = blocking(lint(obj if kind == "profile" else None, obj if kind == "policy" else None))
        if errors:
            raise ValidationFailed("the document has lint errors and cannot be published",
                                   details={"issues": [e.to_dict() for e in errors]})
        # segregation of duties: the author may not publish their own version when another eligible person exists
        if rec.get("created_by_id") == p.id and self._other_publishers(p) > 0:
            raise Forbidden("a different member with publish rights must publish this version (segregation of duties)",
                            code="segregation_of_duties")
        for v in self._versions(p.tenant_id, kind, cid):
            if v["status"] == "published":
                v["status"] = "retired"
                self.d.db.put("configs", v, tenant_id=p.tenant_id)
        rec["status"] = "published"
        rec["published_by"] = p.actor
        rec["published_at"] = self.d.now().isoformat()
        rec["self_published"] = rec.get("created_by_id") == p.id
        self.d.db.put("configs", rec, tenant_id=p.tenant_id)
        audit(self.d, p, f"{kind}.published", f"{cid}@{version}", {"self_published": rec["self_published"]})
        return rec

    def _other_publishers(self, p: Principal) -> int:
        n = 0
        for m in self.d.db.find("memberships", tenant_id=p.tenant_id, limit=1000):
            if m["user_id"] != p.id and m["role"] in ("owner", "admin"):
                n += 1
        return n

    def discard_draft(self, p: Principal, kind: str, cid: str) -> None:
        p.require(Permission.POLICIES_WRITE)
        drafts = [v for v in self._versions(p.tenant_id, kind, cid) if v["status"] == "draft"]
        if not drafts:
            raise NotFound("there is no draft", code="draft_not_found")
        self.d.db.delete("configs", drafts[-1]["id"], tenant_id=p.tenant_id)
        audit(self.d, p, f"{kind}.draft_discarded", f"{cid}@{drafts[-1]['version']}")

    # ------------------------------------------------------------------ resolution (used by runs)
    def resolve(self, tenant_id: str, kind: str, cid: str, version: int | None = None, *, allow_draft: bool = False
                ) -> tuple[Any, int, dict[str, Any]]:
        versions = self._versions(tenant_id, kind, cid)
        if versions:
            cand = [v for v in versions if (version is None and (v["status"] == "published"
                                                                 or (allow_draft and v["status"] == "draft")))
                    or (version is not None and v["version"] == version and v["status"] != "draft")
                    or (version is not None and v["version"] == version and allow_draft)]
            if not cand:
                raise NotFound(f"no published {kind} '{cid}'" + (f" version {version}" if version else ""),
                               code="config_not_found")
            v = cand[-1]
            return self._parse(kind, v["document"], cid), v["version"], v["document"]
        builtin = self.d.catalog.get(kind, cid)
        if builtin is None or (version not in (None, 1)):
            raise NotFound(f"{kind} '{cid}' not found", code="config_not_found")
        return builtin[0], 1, builtin[1]
