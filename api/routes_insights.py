"""Insights, finding feedback, policy test suites, profile suggestion and asset history."""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from ..contracts import requests as R
from .http import Ctx, Reply, api, read_input

# ------------------------------------------------------------------ insights
@api("GET", "/insights")
def insights(c: Ctx) -> Any:
    return c.svc.insights.overview(c.principal, c.q("days") or 30, c.q("project_id"))


@api("GET", "/insights/metrics")
def insights_metrics(c: Ctx) -> Any:
    return Response(c.svc.insights.metrics_text(c.principal, c.q("days") or 30).encode("utf-8"),
                    media_type="text/plain; version=0.0.4; charset=utf-8")


@api("POST", "/runs/{run_id}/findings/{finding_id}/feedback", body=R.FINDING_FEEDBACK)
def finding_feedback(c: Ctx) -> Any:
    b = c.body
    return Reply(c.svc.insights.rate_finding(c.principal, c.params["run_id"], c.params["finding_id"], b["verdict"], b.get("note", "")), 201)


@api("GET", "/runs/{run_id}/feedback")
def run_feedback(c: Ctx) -> Any:
    return c.svc.insights.feedback_for_run(c.principal, c.params["run_id"])


# ------------------------------------------------------------------ assets
@api("GET", "/assets")
def assets(c: Ctx) -> Any:
    return c.svc.assets.list(c.principal, c.q("project_id"), c.q("q"), c.q("limit") or None, c.q("offset") or None)


@api("GET", "/assets/{asset_id}")
def asset_history(c: Ctx) -> Any:
    return c.svc.assets.history(c.principal, c.params["asset_id"])


# ------------------------------------------------------------------ suites
@api("GET", "/suites")
def suites(c: Ctx) -> Any:
    return c.svc.suites.list(c.principal)


@api("POST", "/suites", body=R.SUITE_CREATE)
def suite_create(c: Ctx) -> Any:
    b = c.body
    return Reply(c.svc.suites.create(c.principal, b["name"], b.get("description", ""), b.get("project_id", "")), 201)


@api("GET", "/suites/{suite_id}")
def suite_get(c: Ctx) -> Any:
    return c.svc.suites.get(c.principal, c.params["suite_id"])


@api("DELETE", "/suites/{suite_id}")
def suite_delete(c: Ctx) -> Any:
    c.svc.suites.delete(c.principal, c.params["suite_id"])
    return {"ok": True}


@api("POST", "/suites/{suite_id}/cases", body=R.SUITE_CASE, payload="upload")
def suite_case_add(c: Ctx) -> Any:
    data, filename, _ = read_input(c)
    b = c.body
    return Reply(c.svc.suites.add_case(
        c.principal, c.params["suite_id"], name=b.get("name") or filename, expected=b.get("expected", ""), content=data,
        filename=filename, expected_codes=b.get("expected_codes") or [], destination=b.get("destination") or "local_index",
        source_class=b.get("source_class") or "unknown", classification=b.get("classification") or "internal",
        metadata=b.get("metadata") or {}, note=b.get("note", "")), 201)


@api("DELETE", "/suites/{suite_id}/cases/{case_id}")
def suite_case_remove(c: Ctx) -> Any:
    c.svc.suites.remove_case(c.principal, c.params["suite_id"], c.params["case_id"])
    return {"ok": True}


@api("POST", "/suites/{suite_id}/run", body=R.SUITE_RUN)
def suite_run(c: Ctx) -> Any:
    b = c.body
    return c.svc.suites.run(c.principal, c.params["suite_id"], profile_id=b.get("profile_id", ""), policy_id=b.get("policy_id", ""),
                            profile=b.get("profile") or None, policy=b.get("policy") or None)


# ------------------------------------------------------------------ profile suggestion
@api("POST", "/profiles/suggest", body=R.SUGGEST_FIELDS, payload="upload")
def profile_suggest(c: Ctx) -> Any:
    data, filename, _ = read_input(c)
    return c.svc.suggestions.suggest(c.principal, content=data, filename=filename, name=c.body.get("name", ""),
                                     task=c.body.get("task", ""))
