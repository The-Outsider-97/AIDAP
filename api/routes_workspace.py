"""Projects, profiles and policies, simulation, destinations, baselines, schedules."""

from __future__ import annotations

from typing import Any

from ..contracts import requests as R
from ..domain.utils.domain_errors import NotFound, ValidationFailed
from .http import Ctx, Reply, api, read_input


# ------------------------------------------------------------------ projects
@api("GET", "/projects")
def projects(c: Ctx) -> Any:
    return c.svc.projects.list(c.principal, include_archived=c.q("archived") == "true")


@api("POST", "/projects", body=R.PROJECT_CREATE)
def project_create(c: Ctx) -> Any:
    return Reply(c.svc.projects.create(c.principal, c.body), 201)


@api("GET", "/projects/{project_id}")
def project_get(c: Ctx) -> Any:
    return c.svc.projects.get(c.principal, c.params["project_id"])


@api("PATCH", "/projects/{project_id}", body=R.PROJECT_UPDATE)
def project_update(c: Ctx) -> Any:
    return c.svc.projects.update(c.principal, c.params["project_id"], {k: v for k, v in c.body.items() if k in c.present})


# ------------------------------------------------------------------ profiles & policies
def _kind(c: Ctx) -> str:
    return "profile" if c.req.url.path.split("/")[3] == "profiles" else "policy"


def both(method: str, suffix: str, **kw: Any):
    """Register one handler for /profiles<suffix> and /policies<suffix> (literal paths, so they never shadow other routes)."""
    def deco(fn):
        for k in ("profiles", "policies"):
            api(method, f"/{k}{suffix}", **kw)(fn)
        return fn
    return deco


@both("GET", "")
def config_list(c: Ctx) -> Any:
    return c.svc.configs.list(c.principal, _kind(c))


@both("POST", "", body=R.CONFIG_CREATE)
def config_create(c: Ctx) -> Any:
    b = c.body
    return Reply(c.svc.configs.create(c.principal, _kind(c), b["id"], b["name"], b["document"], b.get("note", "")), 201)


@both("GET", "/{cid}")
def config_get(c: Ctx) -> Any:
    return c.svc.configs.get(c.principal, _kind(c), c.params["cid"])


@both("POST", "/{cid}/versions", body=R.CONFIG_VERSION)
def config_add_version(c: Ctx) -> Any:
    return Reply(c.svc.configs.add_version(c.principal, _kind(c), c.params["cid"], c.body["document"], c.body.get("note", "")), 201)


@both("PUT", "/{cid}/draft", body=R.CONFIG_VERSION)
def config_update_draft(c: Ctx) -> Any:
    return c.svc.configs.update_draft(c.principal, _kind(c), c.params["cid"], c.body["document"], c.body.get("note", ""))


@both("DELETE", "/{cid}/draft")
def config_discard_draft(c: Ctx) -> Any:
    c.svc.configs.discard_draft(c.principal, _kind(c), c.params["cid"])
    return {"ok": True}


@both("POST", "/{cid}/versions/{version}/publish", body=R.PUBLISH_GATE)
def config_publish(c: Ctx) -> Any:
    try:
        v = int(c.params["version"])
    except ValueError as exc:
        raise ValidationFailed("version must be a number") from exc
    gate = None
    if c.body.get("suite_ids"):          # optional regression gate: every named suite must pass against the draft first
        gate = c.svc.suites.gate(c.principal, _kind(c), c.params["cid"], v, c.body["suite_ids"],
                                 profile_id=c.body.get("profile_id", ""), policy_id=c.body.get("policy_id", ""))
    rec = c.svc.configs.publish(c.principal, _kind(c), c.params["cid"], v)
    return {**rec, "suite_gate": gate} if gate else rec


@api("POST", "/lint", body=R.LINT)
def lint(c: Ctx) -> Any:
    from ..domain.governance.authorization import Permission
    c.principal.require(Permission.POLICIES_READ)
    if not c.body.get("profile") and not c.body.get("policy"):
        raise ValidationFailed("provide a profile and/or a policy document")
    return c.svc.configs.lint_documents(c.body.get("profile"), c.body.get("policy"))


@api("POST", "/simulate", body=R.SIMULATE_FIELDS, payload="upload")
def simulate(c: Ctx) -> Any:
    data, name, _ = read_input(c)
    b = c.body
    return c.svc.simulation.simulate(c.principal, content=data, filename=name, profile=b.get("profile") or None,
                                     profile_id=b.get("profile_id", ""), policy=b.get("policy") or None, policy_id=b.get("policy_id", ""),
                                     destination=b.get("destination") or "local_index", source_class=b.get("source_class") or "unknown",
                                     classification=b.get("classification") or "internal", metadata=b.get("metadata") or {})


# ------------------------------------------------------------------ destinations
@api("GET", "/destinations")
def destinations(c: Ctx) -> Any:
    return c.svc.destinations.list(c.principal, c.q("project_id"))


@api("POST", "/destinations", body=R.DESTINATION_CREATE)
def destination_create(c: Ctx) -> Any:
    return Reply(c.svc.destinations.create(c.principal, c.body), 201)


@api("PATCH", "/destinations/{dest_id}", body=R.DESTINATION_UPDATE)
def destination_update(c: Ctx) -> Any:
    return c.svc.destinations.update(c.principal, c.params["dest_id"], {k: v for k, v in c.body.items() if k in c.present})


@api("DELETE", "/destinations/{dest_id}")
def destination_delete(c: Ctx) -> Any:
    c.svc.destinations.delete(c.principal, c.params["dest_id"])
    return {"ok": True}


# ------------------------------------------------------------------ baselines
@api("GET", "/baselines")
def baselines(c: Ctx) -> Any:
    return c.svc.baselines.list(c.principal, c.q("project_id"), c.q("profile_id"))


@api("POST", "/baselines", body=R.BASELINE_PROPOSE)
def baseline_propose(c: Ctx) -> Any:
    return Reply(c.svc.baselines.propose(c.principal, c.body["run_id"], c.body.get("name", "")), 201)


@api("GET", "/baselines/{baseline_id}")
def baseline_get(c: Ctx) -> Any:
    return c.svc.baselines.get(c.principal, c.params["baseline_id"])


@api("POST", "/baselines/{baseline_id}/approve")
def baseline_approve(c: Ctx) -> Any:
    return c.svc.baselines.approve(c.principal, c.params["baseline_id"])


@api("POST", "/baselines/{baseline_id}/retire")
def baseline_retire(c: Ctx) -> Any:
    return c.svc.baselines.retire(c.principal, c.params["baseline_id"])


# ------------------------------------------------------------------ schedules
@api("GET", "/schedules")
def schedules(c: Ctx) -> Any:
    return c.svc.schedules.list(c.principal)


@api("POST", "/schedules", body=R.SCHEDULE_CREATE)
def schedule_create(c: Ctx) -> Any:
    return Reply(c.svc.schedules.create(c.principal, c.body), 201)


@api("PATCH", "/schedules/{sid}", body=R.SCHEDULE_UPDATE)
def schedule_update(c: Ctx) -> Any:
    return c.svc.schedules.update(c.principal, c.params["sid"], {k: v for k, v in c.body.items() if k in c.present})


@api("DELETE", "/schedules/{sid}")
def schedule_delete(c: Ctx) -> Any:
    c.svc.schedules.delete(c.principal, c.params["sid"])
    return {"ok": True}
