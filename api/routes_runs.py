"""Runs, review, quarantine, alerts, audit, deliveries, usage, billing, dashboard."""

from __future__ import annotations

import re
import time
from typing import Any

from starlette.responses import Response

from ..contracts import requests as R
from ..domain.governance.authorization import Permission
from ..domain.utils.domain_errors import ValidationFailed
from ..reporting import render
from .http import Ctx, Reply, api, read_input

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _attachment(name: str, default: str) -> str:
    safe = _SAFE_NAME.sub("_", name or default)[:120].strip("._") or default
    return f'attachment; filename="{safe}"'


# ------------------------------------------------------------------ runs
@api("GET", "/runs")
def runs_list(c: Ctx) -> Any:
    return c.svc.runs.list(c.principal, project_id=c.q("project_id"), decision=c.q("decision"), state=c.q("state"),
                           q=c.q("q")[:100], limit=c.q("limit") or None, offset=c.q("offset") or None)


@api("POST", "/runs", body=R.RUN_JSON, payload="upload")
def run_submit(c: Ctx) -> Any:
    data, name, ctype = read_input(c)
    b, p = c.body, c.principal
    run = c.svc.runs.submit(
        p, project_id=b["project_id"], data=data, filename=name, media_type=ctype, profile_id=b.get("profile_id", ""),
        policy_id=b.get("policy_id", ""), destination_id=b.get("destination_id", ""), source_class=b.get("source_class") or "unknown",
        classification=b.get("classification") or "internal", label=b.get("label", ""),
        idempotency_key=b.get("idempotency_key") or c.req.headers.get("idempotency-key", "")[:120],
        asset_name=b.get("asset_name", ""), metadata=b.get("metadata") or {}, source="api" if p.kind == "api_key" else "ui")
    waited = False
    if b.get("wait") and c.svc.deps.settings.inline_workers:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            cur = c.svc.runs.get(p, run["id"]) if p.can(Permission.RUNS_READ) else run
            if cur["state"] in ("completed", "failed", "cancelled"):
                run, waited = cur, True
                break
            time.sleep(0.25)
    done = run.get("state") in ("completed", "failed", "cancelled")
    return Reply(run, 200 if (run.get("idempotent_replay") or done) else 202,
                 headers={"Location": f"/api/v1/runs/{run['id']}"} | ({"X-Waited": "1"} if waited else {}))


@api("GET", "/runs/{run_id}")
def run_get(c: Ctx) -> Any:
    return c.svc.runs.get(c.principal, c.params["run_id"])


@api("GET", "/runs/{run_id}/stages")
def run_stages(c: Ctx) -> Any:
    return c.svc.runs.stages(c.principal, c.params["run_id"])


@api("GET", "/runs/{run_id}/decisions")
def run_decisions(c: Ctx) -> Any:
    return c.svc.runs.decisions(c.principal, c.params["run_id"])


@api("GET", "/runs/{run_id}/findings")
def run_findings(c: Ctx) -> Any:
    return c.svc.runs.findings(c.principal, c.params["run_id"], severity=c.q("severity"), check_id=c.q("check"),
                               category=c.q("category"), code=c.q("code"))


@api("DELETE", "/runs/{run_id}/content")
def run_content_delete(c: Ctx) -> Any:
    return c.svc.retention.delete_run_content(c.principal, c.params["run_id"])


@api("GET", "/account/export")
def account_export(c: Ctx) -> Any:
    import json
    data = c.svc.retention.export_tenant(c.principal)
    return Response(json.dumps(data, indent=2, default=str).encode("utf-8"), media_type="application/json",
                    headers={"Content-Disposition": _attachment("aidap-export.json", "export.json")})


@api("GET", "/runs/{run_id}/evidence")
def run_evidence(c: Ctx) -> Any:
    out = c.svc.runs.evidence(c.principal, c.params["run_id"])
    if c.q("download") == "1" and out["bundle"]:
        import json
        return Response(json.dumps(out["bundle"], indent=2).encode(), media_type="application/json",
                        headers={"Content-Disposition": _attachment(f"evidence-{c.params['run_id']}.json", "evidence.json")})
    return out


@api("GET", "/runs/{run_id}/report")
def run_report(c: Ctx) -> Any:
    rep = c.svc.runs.report_data(c.principal, c.params["run_id"])
    fmt = (c.q("format") or "json").lower()
    if fmt not in ("json", "csv", "html", "pdf"):
        raise ValidationFailed("format must be json, csv, html or pdf", details={"fields": {"format": "invalid"}})
    if fmt == "json" and c.q("download") != "1":
        return rep
    body, ctype, ext = render(rep, fmt)
    return Response(body, media_type=ctype, headers={"Content-Disposition": _attachment(f"aidap-report-{c.params['run_id']}.{ext}", f"report.{ext}")})


@api("GET", "/runs/{run_id}/diff")
def run_diff(c: Ctx) -> Any:
    other = c.q("against")
    if not other:
        raise ValidationFailed("pass ?against=<run id>", details={"fields": {"against": "required"}})
    return c.svc.runs.diff(c.principal, c.params["run_id"], other)


@api("GET", "/runs/{run_id}/artifact")
def run_artifact(c: Ctx) -> Any:
    data, ver = c.svc.runs.artifact(c.principal, c.params["run_id"])
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": _attachment(ver.get("filename", ""), "artifact"),
                             "X-Content-Digest": ver["content_digest"]})


@api("GET", "/runs/{run_id}/deliveries")
def run_deliveries(c: Ctx) -> Any:
    return c.svc.delivery.list(c.principal, run_id=c.params["run_id"])


@api("POST", "/runs/{run_id}/cancel")
def run_cancel(c: Ctx) -> Any:
    return c.svc.runs.cancel(c.principal, c.params["run_id"])


@api("POST", "/runs/{run_id}/retry")
def run_retry(c: Ctx) -> Any:
    return c.svc.runs.retry(c.principal, c.params["run_id"])


@api("POST", "/runs/{run_id}/rerun")
def run_rerun(c: Ctx) -> Any:
    return Reply(c.svc.runs.rerun(c.principal, c.params["run_id"]), 202)


@api("POST", "/runs/{run_id}/redact", body={"types": R.lst(R.s(60), max=40), "note": R.s(300)})
def run_redact(c: Ctx) -> Any:
    return Reply(c.svc.runs.redact(c.principal, c.params["run_id"], c.body.get("types") or None), 202)


# ------------------------------------------------------------------ review
@api("GET", "/reviews")
def reviews(c: Ctx) -> Any:
    return c.svc.reviews.list(c.principal, c.q("state"), c.q("project_id"), c.q("assignee"), c.q("limit") or None, c.q("offset") or None)


@api("GET", "/reviews/{review_id}")
def review_get(c: Ctx) -> Any:
    return c.svc.reviews.get(c.principal, c.params["review_id"])


@api("POST", "/reviews/{review_id}/assign", body=R.REVIEW_ASSIGN)
def review_assign(c: Ctx) -> Any:
    return c.svc.reviews.assign(c.principal, c.params["review_id"], c.body["assignee"])


@api("POST", "/reviews/{review_id}/resolve", body=R.REVIEW_RESOLVE)
def review_resolve(c: Ctx) -> Any:
    return c.svc.reviews.resolve(c.principal, c.params["review_id"], c.body)


@api("POST", "/exceptions/{exception_id}/revoke")
def exception_revoke(c: Ctx) -> Any:
    return c.svc.reviews.revoke_exception(c.principal, c.params["exception_id"])


# ------------------------------------------------------------------ quarantine
@api("GET", "/quarantine")
def quarantine(c: Ctx) -> Any:
    return c.svc.quarantine.list(c.principal, c.q("state"), c.q("limit") or None, c.q("offset") or None)


@api("GET", "/quarantine/{qid}")
def quarantine_get(c: Ctx) -> Any:
    return c.svc.quarantine.get(c.principal, c.params["qid"])


@api("POST", "/quarantine/{qid}/access", body=R.QUARANTINE_ACCESS)
def quarantine_access(c: Ctx) -> Any:
    return c.svc.quarantine.access(c.principal, c.params["qid"], c.body["purpose"])


@api("GET", "/quarantine/{qid}/content")
def quarantine_content(c: Ctx) -> Any:
    data, run_id = c.svc.quarantine.fetch(c.principal, c.params["qid"], c.q("access_id"))
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": _attachment(f"quarantined-{run_id}.bin", "quarantined.bin")})


@api("POST", "/quarantine/{qid}/dispose", body=R.QUARANTINE_DISPOSE)
def quarantine_dispose(c: Ctx) -> Any:
    return c.svc.quarantine.dispose(c.principal, c.params["qid"], c.body["action"], c.body["comment"])


# ------------------------------------------------------------------ alerts, audit, deliveries
@api("GET", "/alerts")
def alerts(c: Ctx) -> Any:
    return c.svc.alerts.list(c.principal, open_only=c.q("open", "true") != "false", limit=c.q("limit") or 100,
                             offset=c.q("offset") or 0)


@api("POST", "/alerts/{alert_id}/ack", body=R.ALERT_ACK)
def alert_ack(c: Ctx) -> Any:
    return c.svc.alerts.acknowledge(c.principal, c.params["alert_id"], c.body.get("note", ""))


@api("GET", "/audit")
def audit_list(c: Ctx) -> Any:
    return c.svc.audit.list(c.principal, c.q("limit") or 100, c.q("offset") or 0, c.q("action")[:60])


@api("GET", "/audit/verify")
def audit_verify(c: Ctx) -> Any:
    return c.svc.audit.verify(c.principal)


@api("GET", "/audit/export")
def audit_export(c: Ctx) -> Any:
    return Response(c.svc.audit.export_csv(c.principal).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": _attachment("aidap-audit.csv", "audit.csv")})


@api("GET", "/deliveries")
def deliveries(c: Ctx) -> Any:
    return c.svc.delivery.list(c.principal, c.q("run_id"), c.q("state"), c.q("limit") or None, c.q("offset") or None)


@api("POST", "/deliveries/{delivery_id}/retry")
def delivery_retry(c: Ctx) -> Any:
    return c.svc.delivery.retry(c.principal, c.params["delivery_id"])


# ------------------------------------------------------------------ usage & billing
@api("GET", "/usage")
def usage(c: Ctx) -> Any:
    return c.svc.usage.summary(c.principal, c.q("period") or None)


@api("GET", "/usage/history")
def usage_history(c: Ctx) -> Any:
    try:
        months = int(c.q("months") or 6)
    except ValueError:
        months = 6
    return c.svc.usage.history(c.principal, months)


@api("GET", "/billing")
def billing(c: Ctx) -> Any:
    return c.svc.billing.state(c.principal)


@api("POST", "/billing/checkout", body=R.CHECKOUT)
def billing_checkout(c: Ctx) -> Any:
    if c.body["plan_id"] == "developer":
        return c.svc.billing.cancel(c.principal)                    # choosing the free plan = cancel at period end
    return c.svc.billing.checkout(c.principal, c.body["plan_id"])


@api("POST", "/billing/portal")
def billing_portal(c: Ctx) -> Any:
    return c.svc.billing.portal(c.principal)


@api("POST", "/billing/cancel")
def billing_cancel(c: Ctx) -> Any:
    return c.svc.billing.cancel(c.principal)


@api("POST", "/billing/topup", body=R.TOPUP)
def billing_topup(c: Ctx) -> Any:
    return c.svc.billing.topup(c.principal, c.body["amount_cents"])


@api("POST", "/billing/settings", body=R.BILLING_SETTINGS)
def billing_settings(c: Ctx) -> Any:
    return c.svc.billing.settings(c.principal, c.body)


@api("POST", "/billing/sandbox/complete", body={"session_id": R.s(80, required=True)})
def billing_sandbox_complete(c: Ctx) -> Any:
    return c.svc.billing.sandbox_complete(c.principal, c.body["session_id"])


# ------------------------------------------------------------------ dashboard & system
@api("GET", "/dashboard")
def dashboard(c: Ctx) -> Any:
    return c.svc.dashboard.overview(c.principal, c.q("project_id"))


@api("GET", "/system/status")
def system_status(c: Ctx) -> Any:
    d = c.svc.deps
    c.principal.require(Permission.RUNS_READ)
    slai = d.slai.health() if d.slai is not None else {"enabled": False}
    return {"slai": slai, "checkpointing": d.checkpoints.health(), "malware_scanner": d.scanner.health(),
            "queue": d.queue.stats(), "billing": d.billing.health()}
