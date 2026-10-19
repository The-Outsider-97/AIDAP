"""Insights, finding feedback, review SLA, asset history, policy test suites, profile suggestion, publish gate."""

from __future__ import annotations

import json
import unittest

from ..domain.utils.domain_errors import Conflict, FeatureNotInPlan, Forbidden, NotFound, ValidationFailed
from ..api import create_app
from .helpers import CLEAN, META, PASSWORD, PII, SECRET, Env, doc
from .http_client import Client, Server

CSV = ("id,amount,country,note\n" + "\n".join(f"{i},{10 + i % 7}.5,{['NL','DE','FR'][i % 3]},Row {i} was reviewed by the finance team on the closing call" for i in range(40))).encode()


class Insights(unittest.TestCase):
    def setUp(self) -> None:
        self.e = Env("team")
        self.s, self.o = self.e.s, self.e.owner

    def test_overview_counts_decisions_and_review_outcomes(self):
        rev = self.e.add_member("rev@example.com", "reviewer")
        self.e.submit(self.o, CLEAN)
        self.e.submit(self.o, SECRET)
        held = self.e.submit(self.o, PII, meta={})
        self.s.reviews.resolve(rev, held["review_id"], {"resolution": "approve_exception", "days": 7,
                                                        "comment": "Public helpdesk contact, confirmed with HR."})
        o = self.s.insights.overview(self.o, 30)
        self.assertEqual(o["runs"]["finished"], 3)
        self.assertEqual(o["runs"]["by_decision"].get("block"), 1)
        self.assertEqual(o["review"]["resolved"], 1)
        self.assertEqual(o["review"]["overturn_rate"], 1.0)
        self.assertIsNotNone(o["review"]["time_to_resolve_hours"]["median"])
        self.assertEqual(o["reliability"]["mandatory_check_completion"], 1.0)
        self.assertEqual(o["reliability"]["unhandled_errors"], 0)
        self.assertEqual(o["review"]["held_quarantine"], 1)
        self.assertIn("review_overturn_rate", o["definitions"])
        self.assertTrue(any(c["check_id"] == "privacy.pii" and c["findings"] for c in o["checks"]))

    def test_feedback_is_per_person_visible_in_insights_and_never_alters_the_decision(self):
        run = self.e.submit(self.o, PII, meta={})
        f = self.s.runs.findings(self.o, run["id"])["findings"]
        pii = next(x for x in f if x["code"].startswith("privacy.pii"))
        before = self.s.runs.get(self.o, run["id"])["decision"]
        self.s.insights.rate_finding(self.o, run["id"], pii["id"], "false_positive", "helpdesk number")
        self.s.insights.rate_finding(self.o, run["id"], pii["id"], "useful")      # same person may change their rating
        fb = self.s.insights.feedback_for_run(self.o, run["id"])
        self.assertEqual([x["verdict"] for x in fb], ["useful"])
        self.assertEqual(self.s.runs.get(self.o, run["id"])["decision"], before)
        o = self.s.insights.overview(self.o)
        self.assertEqual(o["feedback"]["verdicts"]["useful"], 1)
        row = next(c for c in o["checks"] if c["check_id"] == "privacy.pii")
        self.assertEqual(row["usefulness"], 1.0)
        with self.assertRaises(ValidationFailed):
            self.s.insights.rate_finding(self.o, run["id"], pii["id"], "great")
        with self.assertRaises(NotFound):
            self.s.insights.rate_finding(self.o, run["id"], "f_missing", "useful")
        viewer = self.e.add_member("view@example.com", "viewer")
        with self.assertRaises(Forbidden):
            self.s.insights.rate_finding(viewer, run["id"], pii["id"], "useful")

    def test_overdue_reviews_raise_one_alert_and_never_release(self):
        self.e.submit(self.o, PII, meta={})
        self.s.auth.update_tenant(self.o, None, None, False, review_sla_hours=24)
        self.assertEqual(self.s.insights.sweep_overdue(), 0)
        self.e.clock.advance(hours=30)
        self.assertEqual(self.s.insights.sweep_overdue(), 1)
        self.s.insights.sweep_overdue()
        alerts = [a for a in self.s.alerts.list(self.o) if a["kind"] == "review_overdue"]
        self.assertEqual(len(alerts), 1)
        o = self.s.insights.overview(self.o)
        self.assertEqual((o["review"]["overdue"], o["review"]["sla_hours"]), (1, 24))
        self.assertEqual(o["review"]["open"], 1)

    def test_prometheus_export_is_plan_gated_and_well_formed(self):
        self.e.submit(self.o, CLEAN)
        text = self.s.insights.metrics_text(self.o)
        self.assertIn('aidap_runs{decision="pass"} 1', text)
        for line in text.splitlines():
            self.assertTrue(line.startswith("#") or line.split(" ")[0].replace("{", "").replace("}", "") != "")
        small = Env("starter")
        with self.assertRaises(FeatureNotInPlan):
            small.s.insights.metrics_text(small.owner)

    def test_asset_history_shows_versions_and_reasons_over_time(self):
        self.e.submit(self.o, PII, meta={}, asset_name="handbook.json")
        self.e.submit(self.o, CLEAN, asset_name="handbook.json")
        a = self.s.assets.list(self.o)
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["runs"], a[0]["versions"]), (2, 2))
        h = self.s.assets.history(self.o, a[0]["id"])
        self.assertEqual([t["decision"] for t in h["timeline"]], ["review", "pass"])
        self.assertTrue(h["timeline"][1]["cleared_reasons"])
        self.assertEqual(h["timeline"][0]["cleared_reasons"], [])


class Suites(unittest.TestCase):
    def setUp(self) -> None:
        self.e = Env("team")
        self.s, self.o = self.e.s, self.e.owner

    def suite(self):
        su = self.s.suites.create(self.o, "RAG regression", "adjudicated examples")
        j = lambda x: json.dumps(x).encode()
        add = lambda n, exp, payload, **kw: self.s.suites.add_case(self.o, su["id"], name=n, expected=exp, content=j(payload), filename="d.json",
                                                                  source_class="internal_doc", metadata=META, **kw)
        add("clean policy text", "pass", CLEAN)
        add("credential in text", "block", SECRET, expected_codes=["privacy.secret.api_secret"])
        return su, add

    def test_a_suite_reports_per_example_results_and_direction(self):
        su, add = self.suite()
        res = self.s.suites.run(self.o, su["id"], profile_id="rag_indexing")
        self.assertEqual(res["summary"]["total"], 2)
        self.assertTrue(res["summary"]["all_passed"], res["cases"])
        add("mislabelled", "pass", SECRET)                                        # adjudicated wrongly -> a clear failure
        res2 = self.s.suites.run(self.o, su["id"], profile_id="rag_indexing")
        bad = [c for c in res2["cases"] if not c["ok"]]
        self.assertEqual(len(bad), 1)
        self.assertEqual((bad[0]["expected"], bad[0]["actual"], bad[0]["direction"]), ("pass", "block", "stricter"))
        self.assertEqual(res2["summary"]["stricter_than_expected"], 1)

    def test_loosening_a_policy_is_caught_before_publication(self):
        su, add = self.suite()
        add("personal data held for review", "review", PII)
        loose = {"id": "mine", "name": "Mine", "mode": "enforce", "exceptions": [], "severity_effects": {
            "critical": "quarantine", "high": "pass", "medium": "pass", "low": "pass", "info": "pass"}}
        self.s.configs.create(self.o, "policy", "mine", "Mine", loose)
        with self.assertRaises(Conflict) as cm:
            self.s.suites.gate(self.o, "policy", "mine", 1, [su["id"]], profile_id="rag_indexing")
        self.assertEqual(cm.exception.code, "suite_failed")
        failing = cm.exception.details["failing"]
        self.assertEqual([(c["expected"], c["actual"], c["direction"]) for c in failing], [("review", "pass", "looser")])

    def test_runs_keep_history_and_flag_changes(self):
        su, _ = self.suite()
        self.s.suites.run(self.o, su["id"], profile_id="rag_indexing")
        second = self.s.suites.run(self.o, su["id"], profile_id="rag_indexing")
        self.assertEqual(second["summary"]["changed_since_last_run"], 0)
        self.assertEqual(len(self.s.suites.get(self.o, su["id"])["runs"]), 2)

    def test_limits_content_privacy_and_plan(self):
        su, _ = self.suite()
        got = self.s.suites.get(self.o, su["id"])
        self.assertNotIn("blob_ref", json.dumps(got))
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", json.dumps(self.s.suites.run(self.o, su["id"], profile_id="rag_indexing")))
        with self.assertRaises(ValidationFailed):
            self.s.suites.add_case(self.o, su["id"], name="x", expected="maybe", content=b"x")
        self.s.suites.delete(self.o, su["id"])
        self.assertEqual(self.s.suites.list(self.o), [])
        dev = Env("developer")
        with self.assertRaises(FeatureNotInPlan):
            dev.s.suites.create(dev.owner, "x")
        viewer = self.e.add_member("v@example.com", "viewer")
        with self.assertRaises(Forbidden):
            self.s.suites.create(viewer, "nope")


class Suggestions(unittest.TestCase):
    def test_a_csv_sample_becomes_a_lint_clean_draft_profile(self):
        e = Env("starter")
        out = e.s.suggestions.suggest(e.owner, content=CSV, filename="payments.csv", name="Payments")
        p = out["profile"]
        self.assertFalse(out["stored"])
        self.assertEqual(out["lint"]["errors"], 0, out["lint"])
        by = {f["name"]: f for f in p["fields"]}
        self.assertTrue(by["id"].get("required"))
        self.assertEqual(by["country"].get("domain"), ["DE", "FR", "NL"])
        self.assertLess(by["amount"]["min"], 10.5)
        self.assertGreater(by["amount"]["max"], 16.5)
        self.assertEqual(e.s.deps.db.count("configs", tenant_id=e.tenant), 0)

    def test_free_text_follows_the_document_pattern(self):
        e = Env("starter")
        out = e.s.suggestions.suggest(e.owner, content=b"Employees accrue twenty five days of paid leave each year.", filename="policy.txt")
        self.assertIn("owner", out["profile"]["required_metadata"])
        self.assertEqual(out["lint"]["errors"], 0, out["lint"])

    def test_sensitive_data_in_the_sample_is_reported_not_allowed(self):
        e = Env("starter")
        out = e.s.suggestions.suggest(e.owner, content=b"id,email\n1,anna@example.org\n2,bo@example.org\n", filename="u.csv")
        self.assertIn("email", out["sensitive_types"])
        self.assertEqual(out["profile"]["privacy"]["allowed_types"], [])


class InsightsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = Env("team", overrides={"limits": {"login_rate_per_minute": 1000}})
        cls.srv = Server(create_app(cls.e.s))
        cls.c = Client(cls.srv.base)
        r = cls.c.post("/api/v1/auth/login", {"email": "owner@example.com", "password": PASSWORD})
        assert r.status == 200, r.text
        cls.proj = cls.c.get("/api/v1/projects").json()[0]["id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.stop()

    def test_suite_lifecycle_and_publish_gate_over_http(self):
        c = self.c
        su = c.post("/api/v1/suites", {"name": "Gate"}).json()
        ok = c.post(f"/api/v1/suites/{su['id']}/cases", {"name": "clean", "expected": "pass", "filename": "d.json",
                                                         "source_class": "internal_doc", "metadata": META,
                                                         "content": json.dumps(CLEAN)})
        self.assertEqual(ok.status, 201, ok.text)
        up = c.upload(f"/api/v1/suites/{su['id']}/cases", {"expected": "block", "name": "secret", "source_class": "internal_doc",
                                                           "expected_codes": json.dumps(["privacy.secret.api_secret"])},
                      "s.json", json.dumps(SECRET).encode())
        self.assertEqual(up.status, 201, up.text)
        self.assertEqual(up.json()["expected_codes"], ["privacy.secret.api_secret"])
        csv = c.upload(f"/api/v1/suites/{su['id']}/cases", {"expected": "pass", "name": "csvcodes", "expected_codes": "a.b, c.d"},
                       "t.json", json.dumps(CLEAN).encode())
        self.assertEqual(csv.json()["expected_codes"], ["a.b", "c.d"])
        self.assertEqual(c.request("DELETE", f"/api/v1/suites/{su['id']}/cases/{csv.json()['id']}").status, 200)
        run = c.post(f"/api/v1/suites/{su['id']}/run", {"profile_id": "rag_indexing"})
        self.assertEqual(run.status, 200, run.text)
        self.assertEqual(run.json()["summary"]["total"], 2)
        detail = c.get(f"/api/v1/suites/{su['id']}").json()
        self.assertEqual((len(detail["cases"]), len(detail["runs"])), (2, 1))
        self.assertEqual(c.post(f"/api/v1/suites/{su['id']}/run", {}).status, 422)
        # a profile draft that would let the clean example fail blocks publication
        prof = json.loads(json.dumps({"id": "gated", "name": "Gated", "task": "rag_indexing", "destinations": ["local_index"],
                                      "source_classes": ["internal_doc"], "required_metadata": ["owner", "source_revision", "effective_date"],
                                      "required_checks": ["intake.format", "quality.metadata"], "fields": [
                                          {"name": "title", "type": "string", "required": True, "pattern": "^ZZZ"}]}))
        created = c.post("/api/v1/profiles", {"id": "gated", "name": "Gated", "document": prof})
        self.assertEqual(created.status, 201, created.text)
        blocked = c.post("/api/v1/profiles/gated/versions/1/publish", {"suite_ids": [su["id"]]})
        self.assertEqual(blocked.status, 409, blocked.text)
        self.assertEqual(blocked.json()["error"]["code"], "suite_failed")
        self.assertEqual(c.get("/api/v1/profiles/gated").json()["versions"][0]["status"], "draft")
        self.assertEqual(c.request("DELETE", f"/api/v1/suites/{su['id']}").status, 200)

    def test_insights_metrics_feedback_assets_and_suggestion(self):
        c = self.c
        r = c.upload("/api/v1/runs", {"project_id": self.proj, "profile_id": "rag_indexing", "source_class": "internal_doc",
                                      "metadata": json.dumps(META), "wait": "true", "asset_name": "faq.json"}, "faq.json", json.dumps(CLEAN).encode())
        self.assertIn(r.status, (200, 201, 202), r.text)
        self.e.s.drain()
        run_id = r.json()["id"]
        ins = c.get("/api/v1/insights?days=7")
        self.assertEqual(ins.status, 200)
        self.assertGreaterEqual(ins.json()["runs"]["finished"], 1)
        m = c.get("/api/v1/insights/metrics")
        self.assertEqual(m.status, 200)
        self.assertIn("text/plain", m.headers["content-type"])
        self.assertIn("aidap_runs", m.text)
        fnd = c.get(f"/api/v1/runs/{run_id}/findings").json()["findings"]
        if fnd:
            fb = c.post(f"/api/v1/runs/{run_id}/findings/{fnd[0]['id']}/feedback", {"verdict": "useful"})
            self.assertEqual(fb.status, 201, fb.text)
            self.assertEqual(len(c.get(f"/api/v1/runs/{run_id}/feedback").json()), 1)
        self.assertEqual(c.post(f"/api/v1/runs/{run_id}/findings/f_nope/feedback", {"verdict": "useful"}).status, 404)
        assets = c.get("/api/v1/assets").json()
        self.assertTrue(any(a["name"] == "faq.json" for a in assets))
        hist = c.get(f"/api/v1/assets/{assets[0]['id']}")
        self.assertEqual(hist.status, 200)
        sug = c.upload("/api/v1/profiles/suggest", {"name": "Payments"}, "payments.csv", CSV, "text/csv")
        self.assertEqual(sug.status, 200, sug.text)
        self.assertEqual(sug.json()["lint"]["errors"], 0)
        self.assertEqual(c.request("PATCH", "/api/v1/tenant", json_body={"review_sla_hours": 12}).status, 200)
        self.assertEqual(c.get("/api/v1/insights").json()["review"]["sla_hours"], 12)

    def test_scrape_with_a_read_only_api_key(self):
        k = self.c.post("/api/v1/api-keys", {"name": "prom", "scopes": ["runs:read"]}).json()["token"]
        prom = Client(self.srv.base, bearer=k)
        self.assertEqual(prom.get("/api/v1/insights/metrics").status, 200)
        self.assertEqual(prom.post("/api/v1/suites", {"name": "no"}).status, 403)


if __name__ == "__main__":
    unittest.main()
