"""Operating metrics (whitepaper 7.21/7.23), reviewer feedback on findings, review-SLA monitoring and asset history.

Every figure is computed from records AIDAP already keeps; nothing here changes a decision, a policy or a threshold.
Feedback is an input for people who maintain policies: it never retunes a live policy (whitepaper: learning stays outside
the live decision path).
"""

from __future__ import annotations

from datetime import timedelta
from statistics import median
from typing import Any

from ...domain.accounts.plans import F_METRICS_EXPORT
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import NotFound, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id, parse_iso
from ..context import Principal
from ..utils.common import audit, audit_system, clean_page, get_or_404

__all__ = ["InsightsService", "AssetQueries", "VERDICTS", "DEFAULT_REVIEW_SLA_HOURS", "DEFINITIONS"]

VERDICTS = ("useful", "false_positive", "unclear")
DEFAULT_REVIEW_SLA_HOURS = 72
MAX_RUNS = 5000
ARTIFACT_SAMPLE = 300

DEFINITIONS = {
    "mandatory_check_completion": "Share of finished runs in which every mandatory check produced a result.",
    "unsupported_input_rate": "Share of sampled runs whose input format could not be read.",
    "unhandled_errors": "Runs that ended in the failed state instead of producing a decision.",
    "review_overturn_rate": "Share of resolved reviews where a reviewer approved a scoped exception.",
    "time_to_resolve_hours": "Hours from a review opening to its resolution (median and 90th percentile).",
    "integrity_stops": "Releases stopped at send time because the artifact digest no longer matched the decision.",
    "finding_usefulness": "Share of rated findings that reviewers marked useful. Reviewer opinion, not measured accuracy.",
}


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


class InsightsService:
    def __init__(self, deps: Any, plans: Any, alerts: Any) -> None:
        self.d, self.plans, self.alerts = deps, plans, alerts

    # ------------------------------------------------------------------ settings
    def review_sla_hours(self, tenant_id: str) -> int:
        t = self.d.db.get("tenants", tenant_id, tenant_id=tenant_id) or {}
        try:
            return max(1, min(int((t.get("settings") or {}).get("review_sla_hours") or DEFAULT_REVIEW_SLA_HOURS), 720))
        except (TypeError, ValueError):
            return DEFAULT_REVIEW_SLA_HOURS

    # ------------------------------------------------------------------ feedback on findings
    def _finding(self, p: Principal, run_id: str, finding_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        run = get_or_404(self.d, "runs", run_id, p.tenant_id, "run")
        p.require_project(run["project_id"])
        art = self.d.db.get("run_artifacts", run_id, tenant_id=p.tenant_id)
        if art is None:
            raise NotFound("the stored results of this run are no longer available", code="artifact_expired")
        for res in (art.get("results") or {}).values():
            for f in res.get("findings", []):
                if f["id"] == finding_id:
                    return run, f
        raise NotFound("finding not found in this run", code="finding_not_found")

    def rate_finding(self, p: Principal, run_id: str, finding_id: str, verdict: str, note: str = "") -> dict[str, Any]:
        p.require(Permission.FINDINGS_READ)
        if not (p.can(Permission.REVIEWS_RESOLVE) or p.can(Permission.RUNS_SUBMIT)):
            p.require(Permission.REVIEWS_RESOLVE)
        if verdict not in VERDICTS:
            raise ValidationFailed("verdict must be useful, false_positive or unclear", details={"fields": {"verdict": "invalid"}})
        run, f = self._finding(p, run_id, finding_id)
        rec = {"id": new_id("fbk"), "tenant_id": p.tenant_id, "project_id": run["project_id"], "run_id": run_id,
               "finding_id": finding_id, "check_id": f["check_id"], "code": f["code"], "verdict": verdict,
               "note": (note or "").strip()[:300], "actor": p.actor, "created_at": iso(self.d.now()),
               "policy_ref": f"{run['policy_id']}@{run['policy_version']}", "profile_ref": f"{run['profile_id']}@{run['profile_version']}"}
        ukey = f"{p.tenant_id}:{run_id}:{finding_id}:{p.id}"
        prior = self.d.db.get_by_ukey("finding_feedback", ukey)
        if prior:                                                      # one rating per person per finding; they may change it
            rec["id"], rec["created_at"] = prior["id"], prior["created_at"]
            rec["updated_at"] = iso(self.d.now())
        self.d.db.put("finding_feedback", rec, tenant_id=p.tenant_id, ukey=ukey)
        audit(self.d, p, "finding.rated", f"{run_id}:{finding_id}", {"verdict": verdict, "code": f["code"]})
        return rec

    def feedback_for_run(self, p: Principal, run_id: str) -> list[dict[str, Any]]:
        p.require(Permission.FINDINGS_READ)
        run = get_or_404(self.d, "runs", run_id, p.tenant_id, "run")
        p.require_project(run["project_id"])
        rows = self.d.db.find("finding_feedback", tenant_id=p.tenant_id, where={"run_id": run_id}, limit=1000)
        return [{**r, "mine": r["actor"] == p.actor} for r in rows]

    # ------------------------------------------------------------------ overview
    def overview(self, p: Principal, days: Any = 30, project_id: str = "") -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        try:
            days = max(1, min(int(days or 30), 365))
        except (TypeError, ValueError):
            days = 30
        return self._compute(p.tenant_id, days, project_id, p)

    def _compute(self, tenant: str, days: int, project_id: str, p: Principal | None = None) -> dict[str, Any]:
        now = self.d.now()
        since = iso(now - timedelta(days=days))
        where = {"project_id": project_id} if project_id else None

        def visible(pid: str) -> bool:
            return p is None or not pid or p.can_project(pid)

        runs = [r for r in self.d.db.find("runs", tenant_id=tenant, where=where, limit=MAX_RUNS)
                if r["created_at"] >= since and visible(r["project_id"])]
        finished = [r for r in runs if r["state"] == "completed"]
        by_decision: dict[str, int] = {}
        for r in finished:
            by_decision[r.get("decision") or "none"] = by_decision.get(r.get("decision") or "none", 0) + 1
        failed = [r for r in runs if r["state"] == "failed"]

        # findings, unsupported inputs and per-check detail come from stored results of the most recent runs
        sample = [r for r in finished if not r.get("expired")][:ARTIFACT_SAMPLE]
        per_check: dict[str, dict[str, Any]] = {}
        codes: dict[str, dict[str, Any]] = {}
        unsupported = 0
        for r in sample:
            art = self.d.db.get("run_artifacts", r["id"], tenant_id=tenant) or {}
            for cid, res in (art.get("results") or {}).items():
                c = per_check.setdefault(cid, {"check_id": cid, "runs": 0, "failed": 0, "unknown": 0, "findings": 0})
                c["runs"] += 1
                c["failed"] += res.get("status") == "failed"
                c["unknown"] += res.get("status") in ("unknown", "error", "not_evaluated")
                c["findings"] += len(res.get("findings", []))
                for f in res.get("findings", []):
                    e = codes.setdefault(f["code"], {"code": f["code"], "check_id": cid, "count": 0, "runs": 0})
                    e["count"] += int(f.get("count", 1) or 1)
                    e["runs"] += 1
                    if f["code"] == "intake.unsupported_format":
                        unsupported += 1
        mandatory_ok = sum(1 for r in finished if r.get("coverage_ok"))

        # reviews
        reviews = [v for v in self.d.db.find("reviews", tenant_id=tenant, where={"project_id": project_id} if project_id else None,
                                             limit=MAX_RUNS) if visible(v["project_id"])]
        in_window = [v for v in reviews if v["created_at"] >= since]
        resolved = [v for v in in_window if v["state"] == "resolved"]
        overturned = [v for v in resolved if v.get("resolution") == "approve_exception"]
        hours: list[float] = []
        for v in resolved:
            a, b = parse_iso(v["created_at"]), parse_iso(v.get("resolved_at"))
            if a and b:
                hours.append(max((b - a).total_seconds() / 3600, 0.0))
        open_reviews = [v for v in reviews if v["state"] == "open"]
        sla = self.review_sla_hours(tenant)
        ages = [(now - parse_iso(v["created_at"])).total_seconds() / 3600 for v in open_reviews]
        held = [q for q in self.d.db.find("quarantine", tenant_id=tenant, where={"state": "held"}, limit=2000) if visible(q.get("project_id", ""))]

        # deliveries
        deliveries = [d for d in self.d.db.find("deliveries", tenant_id=tenant, where={"project_id": project_id} if project_id else None,
                                                limit=MAX_RUNS) if d["created_at"] >= since and visible(d["project_id"])]
        sent = [d for d in deliveries if d["state"] == "sent"]
        dfail = [d for d in deliveries if d["state"] == "failed"]
        stops = [d for d in dfail if "digest" in (d.get("last_error") or "").lower()]
        retried = [d for d in deliveries if int(d.get("attempts", 0)) > 1]

        # feedback
        fb = [x for x in self.d.db.find("finding_feedback", tenant_id=tenant, limit=MAX_RUNS) if x["created_at"] >= since and visible(x["project_id"])]
        verdicts = {v: sum(1 for x in fb if x["verdict"] == v) for v in VERDICTS}
        fb_by_check: dict[str, dict[str, int]] = {}
        fb_by_code: dict[str, dict[str, int]] = {}
        for x in fb:
            for table, key in ((fb_by_check, x["check_id"]), (fb_by_code, x["code"])):
                row = table.setdefault(key, {v: 0 for v in VERDICTS})
                row[x["verdict"]] += 1
        for c in per_check.values():
            row = fb_by_check.get(c["check_id"], {})
            rated = row.get("useful", 0) + row.get("false_positive", 0)
            c["rated"] = rated
            c["usefulness"] = _rate(row.get("useful", 0), rated)
            c["unknown_rate"] = _rate(c["unknown"], c["runs"])
        for e in codes.values():
            row = fb_by_code.get(e["code"], {})
            rated = row.get("useful", 0) + row.get("false_positive", 0)
            e["rated"], e["false_positive"] = rated, row.get("false_positive", 0)
            e["usefulness"] = _rate(row.get("useful", 0), rated)

        series: dict[str, dict[str, int]] = {}
        for r in finished:
            day = r["created_at"][:10]
            series.setdefault(day, {})
            series[day][r.get("decision") or "none"] = series[day].get(r.get("decision") or "none", 0) + 1

        return {
            "window_days": days, "project_id": project_id or None, "generated_at": iso(now),
            "runs": {"total": len(runs), "finished": len(finished), "by_decision": by_decision,
                     "pass_rate": _rate(by_decision.get("pass", 0), len(finished)),
                     "hold_rate": _rate(len(finished) - by_decision.get("pass", 0), len(finished))},
            "reliability": {
                "unhandled_errors": len(failed), "error_rate": _rate(len(failed), len(runs)),
                "mandatory_check_completion": _rate(mandatory_ok, len(finished)),
                "unsupported_input_rate": _rate(unsupported, len(sample)), "sampled_runs": len(sample),
                "delivery": {"sent": len(sent), "failed": len(dfail), "retried": len(retried), "integrity_stops": len(stops)}},
            "review": {
                "opened": len(in_window), "resolved": len(resolved), "open": len(open_reviews),
                "overturned": len(overturned), "overturn_rate": _rate(len(overturned), len(resolved)),
                "repair_requested": sum(1 for v in resolved if v.get("resolution") == "request_repair"),
                "rejected": sum(1 for v in resolved if v.get("resolution") == "reject"),
                "time_to_resolve_hours": {"median": round(median(hours), 2) if hours else None, "p90": _pct(hours, 0.9)},
                "sla_hours": sla, "overdue": sum(1 for a in ages if a > sla),
                "oldest_open_hours": round(max(ages), 1) if ages else None,
                "held_quarantine": len(held)},
            "feedback": {"total": len(fb), "verdicts": verdicts,
                         "usefulness": _rate(verdicts["useful"], verdicts["useful"] + verdicts["false_positive"])},
            "checks": sorted(per_check.values(), key=lambda c: (-c["findings"], c["check_id"])),
            "top_findings": sorted(codes.values(), key=lambda e: (-e["count"], e["code"]))[:15],
            "series": [{"day": d, **v} for d, v in sorted(series.items())],
            "definitions": DEFINITIONS,
        }

    # ------------------------------------------------------------------ Prometheus text exposition
    def metrics_text(self, p: Principal, days: Any = 30) -> str:
        p.require(Permission.RUNS_READ)
        self.plans.require_feature(p.tenant_id, F_METRICS_EXPORT, "Metrics export")
        o = self.overview(p, days)
        lines: list[str] = []

        def gauge(name: str, help_: str, samples: list[tuple[dict[str, str], float | None]]) -> None:
            lines.append(f"# HELP {name} {help_}")
            lines.append(f"# TYPE {name} gauge")
            for labels, v in samples:
                if v is None:
                    continue
                lab = "{" + ",".join(f'{k}="{val}"' for k, val in labels.items()) + "}" if labels else ""
                lines.append(f"{name}{lab} {v}")

        win = o["window_days"]
        gauge("aidap_runs", f"Finished runs by decision over the last {win} days.",
              [({"decision": d}, n) for d, n in sorted(o["runs"]["by_decision"].items())])
        gauge("aidap_runs_failed", "Runs that ended in the failed state.", [({}, o["reliability"]["unhandled_errors"])])
        gauge("aidap_mandatory_check_completion_ratio", "Share of finished runs with every mandatory check completed.",
              [({}, o["reliability"]["mandatory_check_completion"])])
        gauge("aidap_unsupported_input_ratio", "Share of sampled runs with an unreadable input format.",
              [({}, o["reliability"]["unsupported_input_rate"])])
        gauge("aidap_deliveries", "Deliveries by outcome.", [({"state": "sent"}, o["reliability"]["delivery"]["sent"]),
                                                              ({"state": "failed"}, o["reliability"]["delivery"]["failed"])])
        gauge("aidap_release_integrity_stops", "Releases stopped at send time by a digest mismatch.",
              [({}, o["reliability"]["delivery"]["integrity_stops"])])
        gauge("aidap_reviews_open", "Open human reviews.", [({}, o["review"]["open"])])
        gauge("aidap_reviews_overdue", "Open reviews older than the review SLA.", [({}, o["review"]["overdue"])])
        gauge("aidap_review_oldest_open_hours", "Age of the oldest open review in hours.", [({}, o["review"]["oldest_open_hours"])])
        gauge("aidap_review_overturn_ratio", "Share of resolved reviews where an exception was approved.",
              [({}, o["review"]["overturn_rate"])])
        gauge("aidap_quarantine_held", "Items held in quarantine.", [({}, o["review"]["held_quarantine"])])
        gauge("aidap_findings", "Findings by check over the sampled runs.",
              [({"check": c["check_id"]}, c["findings"]) for c in o["checks"]])
        gauge("aidap_alerts_open", "Unacknowledged alerts.",
              [({}, self.d.db.count("alerts", tenant_id=p.tenant_id, where={"acknowledged_at": None}))])
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ review SLA sweep (housekeeping)
    def sweep_overdue(self) -> int:
        """Raise one deduplicated alert per workspace that has reviews open beyond its SLA. Never changes a review."""
        raised = 0
        now = self.d.now()
        by_tenant: dict[str, list[dict[str, Any]]] = {}
        for v in self.d.db.find("reviews", where={"state": "open"}, limit=MAX_RUNS):
            by_tenant.setdefault(v["tenant_id"], []).append(v)
        for tenant, items in by_tenant.items():
            sla = self.review_sla_hours(tenant)
            late = [v for v in items if (now - parse_iso(v["created_at"])) > timedelta(hours=sla)]
            if not late:
                continue
            self.alerts.raise_alert(tenant, "", "review_overdue", "review_overdue", "Reviews are past their deadline",
                                    f"{len(late)} open review(s) have waited longer than {sla} hours. An unanswered review "
                                    f"never releases the input.", "medium", late[0]["run_id"])
            audit_system(self.d, tenant, "review.sla_breached", "", {"overdue": len(late), "sla_hours": sla})
            raised += 1
        return raised


class AssetQueries:
    """Asset history: every version of a named input, with how its decision and findings changed over time."""

    def __init__(self, deps: Any) -> None:
        self.d = deps

    def list(self, p: Principal, project_id: str = "", q: str = "", limit: Any = None, offset: Any = None) -> list[dict[str, Any]]:
        p.require(Permission.RUNS_READ)
        lim, off = clean_page(limit, offset)
        where = {"project_id": project_id} if project_id else None
        out = []
        for a in self.d.db.find("assets", tenant_id=p.tenant_id, where=where, limit=5000):
            if not p.can_project(a["project_id"]) or (q and q.lower() not in a["name"].lower()):
                continue
            runs = self.d.db.find("runs", tenant_id=p.tenant_id, where={"asset_id": a["id"]}, limit=500)
            if not runs:
                continue
            latest = runs[0]
            dec = [r.get("decision") for r in runs if r.get("decision")]
            out.append({"id": a["id"], "name": a["name"], "project_id": a["project_id"], "runs": len(runs),
                        "versions": len({r["version_id"] for r in runs}), "latest_run": latest["id"],
                        "latest_decision": latest.get("decision"), "latest_state": latest["state"],
                        "last_seen_at": latest["created_at"], "first_seen_at": runs[-1]["created_at"],
                        "passed": sum(1 for d in dec if d == "pass"), "held": sum(1 for d in dec if d != "pass"),
                        "released_to": sorted({r["destination_id"] for r in runs if r.get("destination_id") and r.get("decision") == "pass"})})
        out.sort(key=lambda x: x["last_seen_at"], reverse=True)
        return out[off:off + lim]

    def history(self, p: Principal, asset_id: str) -> dict[str, Any]:
        p.require(Permission.RUNS_READ)
        a = get_or_404(self.d, "assets", asset_id, p.tenant_id, "asset")
        p.require_project(a["project_id"])
        runs = sorted(self.d.db.find("runs", tenant_id=p.tenant_id, where={"asset_id": asset_id}, limit=500),
                      key=lambda r: (r["created_at"], r.get("version_no") or 0))
        versions: dict[str, dict[str, Any]] = {}
        timeline = []
        prev_codes: set[str] | None = None
        for r in runs:
            codes: set[str] = set()
            dec = self.d.db.get("decisions", r["decision_id"], tenant_id=p.tenant_id) if r.get("decision_id") else None
            for reason in (dec or {}).get("reasons", []):
                codes.add(reason["code"])
            v = versions.setdefault(r["version_id"], {"version_id": r["version_id"], "version_no": r.get("version_no"),
                                                       "digest": r["input_digest"], "size": r.get("size"), "runs": 0,
                                                       "first_seen_at": r["created_at"]})
            v["runs"] += 1
            timeline.append({"run_id": r["id"], "created_at": r["created_at"], "version_no": r.get("version_no"),
                             "decision": r.get("decision"), "state": r["state"], "reason_codes": sorted(codes),
                             "new_reasons": sorted(codes - prev_codes) if prev_codes is not None else sorted(codes),
                             "cleared_reasons": sorted(prev_codes - codes) if prev_codes is not None else [],
                             "profile": f"{r['profile_id']}@{r['profile_version']}", "policy": f"{r['policy_id']}@{r['policy_version']}",
                             "destination_id": r.get("destination_id"), "label": r.get("label", ""),
                             "same_content_as_previous": bool(timeline) and timeline[-1]["_digest"] == r["input_digest"],
                             "_digest": r["input_digest"]})
            prev_codes = codes
        for t in timeline:
            t.pop("_digest", None)
        return {"asset": {k: a.get(k) for k in ("id", "name", "project_id", "created_at", "source_class", "classification")},
                "versions": list(versions.values()), "timeline": timeline}
