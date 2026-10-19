"""Machine-readable export of AIDAP's published contracts (written to ``docs/contracts``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.decisions.rationale import REASON_GUIDANCE
from ..domain.evaluations import CHECK_CATALOG
from ..domain.governance.authorization import Permission, ROLE_PERMISSIONS, SCOPE_PERMISSIONS
from ..domain.workflows.stages import STAGES
from .validation import Field
from . import requests as req
from .versions import CONTRACTS

__all__ = ["export_all", "describe_schema"]


def describe_schema(schema: dict[str, Field]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, f in schema.items():
        d: dict[str, Any] = {"type": f.kind, "required": f.required}
        if f.choices:
            d["enum"] = list(f.choices)
        if f.max is not None and f.kind in ("string", "email", "url"):
            d["maxLength"] = int(f.max)
        if f.kind in ("integer", "number"):
            if f.min is not None:
                d["minimum"] = f.min
            if f.max is not None:
                d["maximum"] = f.max
        if f.kind == "list" and f.item is not None:
            d["items"] = describe_schema({"_": f.item})["_"]
        if f.kind == "object" and f.schema:
            d["properties"] = describe_schema(f.schema)
        out[name] = d
    return out


def export_all(target: Path) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def dump(name: str, payload: Any) -> None:
        (target / name).write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        written.append(name)

    dump("versions.json", CONTRACTS)
    dump("requests.json", {n: describe_schema(getattr(req, n)) for n in req.__all__
                           if isinstance(getattr(req, n), dict)})
    dump("checks.json", {cid: {"title": s.title, "category": s.category.value, "stage": s.stage,
                               "origin": s.origin.value, "default_mandatory": s.default_mandatory}
                         for cid, s in CHECK_CATALOG.items()})
    dump("workflow.json", [{"stage": s.no, "key": s.key, "title": s.title, "method": s.method} for s in STAGES])
    dump("reason_guidance.json", [{"prefix": p, "guidance": g} for p, g in REASON_GUIDANCE])
    dump("permissions.json", {"roles": {r.value: sorted(p.value for p in perms)
                                        for r, perms in ROLE_PERMISSIONS.items()},
                              "api_key_scopes": {k: sorted(p.value for p in v) for k, v in SCOPE_PERMISSIONS.items()},
                              "all": sorted(p.value for p in Permission)})
    return written
