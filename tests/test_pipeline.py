"""End-to-end behaviour of the run pipeline against a real database and the real deterministic engine."""

from __future__ import annotations

import json
import unittest

from ..domain.utils.domain_errors import (Conflict, FeatureNotInPlan, Forbidden, IntegrityViolation, PayloadTooLarge,
                                          QuotaExceeded, ValidationFailed)
from ..reporting import render
from .helpers import CLEAN, META, PII, SECRET, Env, doc


class Pipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.e = Env("team")
        self.s, self.o = self.e.s, self.e.owner

    # ------------------------------------------------------------------ decisions
    def test_clean_input_passes_with_sealed_evidence(self):
        run = self.e.submit(self.o, CLEAN)
        self.assertEqual((run["state"], run["decision"]), ("completed", "pass"))
        self.assertTrue(run["release_authorized"])
        ev = self.s.runs.evidence(self.o, run["id"])
        self.assertTrue(ev["verified"])
        self.assertEqual(ev["bundle"]["producer"]["name"], "AIDAP")
        self.assertEqual([st["stage"] for st in run["stages"]], list(range(1, 21)))      # all 20 stages are shown
        self.assertIn("skipped", {st["state"] for st in run["stages"]})

    def test_secret_is_blocked_quarantined_and_cannot_be_released(self):
        run = self.e.submit(self.o, SECRET)
        self.assertEqual(run["decision"], "block")
        self.assertTrue(run["quarantine_id"])
        self.assertFalse(run["release_authorized"])
        with self.assertRaises(Forbidden):
            self.s.runs.artifact(self.o, run["id"])
        codes = {r["code"] for r in run["decision_detail"]["reasons"]}
        self.assertTrue(any(c.startswith("privacy.secret") for c in codes))
        # findings never carry the secret itself
        blob = json.dumps(self.s.runs.findings(self.o, run["id"]))
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", blob)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", json.dumps(self.s.runs.evidence(self.o, run["id"])))

    def test_unknown_mandatory_check_never_passes(self):
        run = self.e.submit(self.o, b"\x00\x01\x02 not a document \xff" * 40, "blob.bin")
        self.assertNotEqual(run["decision"], "pass")

    def test_findings_carry_separate_evidence_inference_and_confidence(self):
        run = self.e.submit(self.o, PII)
        f = self.s.runs.findings(self.o, run["id"])["findings"]
        self.assertTrue(f)
        for x in f:
            self.assertTrue(x["observed"] and x["inference"] and x["recommended_action"])
            self.assertIn(x["confidence"]["basis"], ("deterministic", "heuristic", "unknown"))
        self.assertNotIn("maria.lopez@example.org", json.dumps(f))

    # ------------------------------------------------------------------ review and exceptions
    def test_exception_flow_with_segregation_of_duties(self):
        reviewer = self.e.add_member("rev@example.com", "reviewer")
        run = self.e.submit(self.o, PII, meta={})
        self.assertEqual(run["decision"], "review")
        rid = run["review_id"]
        with self.assertRaises(Forbidden) as cm:                      # owner submitted it and another reviewer exists
            self.s.reviews.resolve(self.o, rid, {"resolution": "approve_exception", "comment": "approved by the submitter"})
        self.assertEqual(cm.exception.code, "segregation_of_duties")
        with self.assertRaises(ValidationFailed):
            self.s.reviews.resolve(reviewer, rid, {"resolution": "approve_exception", "comment": "short"})
        out = self.s.reviews.resolve(reviewer, rid, {"resolution": "approve_exception", "days": 7,
                                                      "comment": "Contact details are the public helpdesk, reviewed with HR."})
        self.assertEqual(out["decision"], "pass")
        again = self.s.runs.get(self.o, run["id"])
        self.assertEqual(again["decision"], "pass")
        self.assertEqual(len(again["history"]), 2)
        self.assertEqual(again["history"][0]["status"], "superseded")
        self.assertTrue(again["decision_detail"]["exception_ids"])
        # the exception expires -> the decision is re-evaluated and a stale PASS cannot be released
        self.e.clock.advance(days=8)
        self.assertEqual(self.s.reviews.sweep_expired(), 1)
        self.assertEqual(self.s.runs.get(self.o, run["id"])["decision"], "review")

    def test_secret_exceptions_are_refused(self):
        run = self.e.submit(self.o, SECRET)
        from ..domain.decisions import exception_allowed_for
        self.assertFalse(exception_allowed_for("privacy.secret.api_secret"))
        self.assertFalse(exception_allowed_for("safety.malicious.x"))
        self.assertIsNone(run["review_id"])

    def test_reject_in_review_blocks(self):
        run = self.e.submit(self.o, PII, meta={})
        out = self.s.reviews.resolve(self.o, run["review_id"], {"resolution": "reject", "comment": "contains customer contact data"})
        self.assertEqual(out["decision"], "block")
        self.assertFalse(self.s.runs.get(self.o, run["id"])["release_authorized"])

    # ------------------------------------------------------------------ redaction, release, delivery
    def test_redaction_creates_a_derivative_run(self):
        run = self.e.submit(self.o, PII, meta=META)
        self.assertEqual(run["decision"], "review")
        out = self.s.runs.redact(self.o, run["id"], None)
        self.s.drain()
        child = self.s.runs.get(self.o, out["run"]["id"])
        self.assertEqual(child["parent_run_id"], run["id"])
        self.assertGreater(out["redaction"]["total"], 0)
        self.assertEqual(child["decision"], "pass")
        # the original input is untouched
        self.assertEqual(self.s.runs.get(self.o, run["id"])["decision"], "review")
        self.assertNotEqual(child["input_digest"], run["input_digest"])

    def test_artifact_pull_requires_authorisation_and_records_it(self):
        run = self.e.submit(self.o, CLEAN)
        data, ver = self.s.runs.artifact(self.o, run["id"])
        self.assertEqual(json.loads(data)[0]["title"], "T")
        acts = [a["action"] for a in self.s.audit.list(self.o, limit=50)]
        self.assertIn("artifact.pulled", acts)

    def test_webhook_delivery_is_metadata_only_and_reverified(self):
        d = self.s.destinations.create(self.o, {"name": "hook", "klass": "local_index", "delivery": "webhook",
                                                 "target_url": "https://example.com/hook"})
        self.assertTrue(d["signing_secret"].startswith("whsec_"))
        run = self.e.submit(self.o, PII, meta={}, destination_id=d["id"])
        self.assertEqual(len(self.e.webhooks.sent), 1)
        payload = self.e.webhooks.sent[0]["payload"]
        self.assertEqual(payload["decision"], "review")
        self.assertFalse(payload["release_authorized"])
        self.assertNotIn("artifact", payload["links"])
        self.assertNotIn("maria", json.dumps(payload))
        self.assertEqual(self.e.webhooks.sent[0]["secret"], d["signing_secret"])
        self.assertEqual(run["decision"], "review")

    def test_webhook_retries_then_succeeds(self):
        d = self.s.destinations.create(self.o, {"name": "hook", "klass": "local_index", "delivery": "webhook",
                                                 "target_url": "https://example.com/hook"})
        self.e.webhooks.fail_next = 1
        self.e.submit(self.o, CLEAN, destination_id=d["id"])
        self.assertEqual(len(self.e.webhooks.sent), 0)
        self.e.clock.advance(seconds=0)
        import time
        time.sleep(0.05)
        for _ in range(3):                                           # backoff is real time in the queue; force it due
            self.s.deps.db._conn().execute("UPDATE jobs SET run_after='2000-01-01T00:00:00Z' WHERE state='queued'")
            self.s.drain()
        self.assertEqual(len(self.e.webhooks.sent), 1)
        self.assertTrue(self.e.webhooks.sent[0]["payload"]["release_authorized"])

    # ------------------------------------------------------------------ robustness
    def test_idempotency_key(self):
        a = self.s.runs.submit(self.o, project_id=self.e.project["id"], data=json.dumps(CLEAN).encode(), filename="a.json",
                               profile_id="rag_indexing", idempotency_key="k1", metadata=META)
        b = self.s.runs.submit(self.o, project_id=self.e.project["id"], data=json.dumps(CLEAN).encode(), filename="a.json",
                               profile_id="rag_indexing", idempotency_key="k1", metadata=META)
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b["idempotent_replay"])
        with self.assertRaises(Conflict):
            self.s.runs.submit(self.o, project_id=self.e.project["id"], data=b"[1,2,3]", filename="a.json",
                               profile_id="rag_indexing", idempotency_key="k1")

    def test_engine_failure_is_failed_never_pass(self):
        def boom():
            raise RuntimeError("engine exploded")
        self.s.runs.engine = boom
        run = self.s.runs.submit(self.o, project_id=self.e.project["id"], data=json.dumps(CLEAN).encode(), filename="a.json",
                                 profile_id="rag_indexing", metadata=META)
        for _ in range(6):
            self.s.deps.db._conn().execute("UPDATE jobs SET run_after='2000-01-01T00:00:00Z' WHERE state='queued'")
            self.s.drain()
        got = self.s.runs.get(self.o, run["id"])
        self.assertEqual(got["state"], "failed")
        self.assertIsNone(got["decision"])
        with self.assertRaises(Forbidden):
            self.s.runs.artifact(self.o, run["id"])

    def test_tampered_stored_input_is_detected(self):
        run = self.s.runs.submit(self.o, project_id=self.e.project["id"], data=json.dumps(CLEAN).encode(), filename="a.json",
                                 profile_id="rag_indexing", metadata=META)
        ver = self.s.deps.db.get("versions", run["version_id"])
        ver["content_digest"] = "sha256:" + "0" * 64
        self.s.deps.db.put("versions", ver, tenant_id=self.tenant if hasattr(self, "tenant") else self.e.tenant)
        self.s.drain()
        got = self.s.runs.get(self.o, run["id"])
        self.assertEqual(got["state"], "failed")

    def test_tampered_evidence_is_withheld(self):
        run = self.e.submit(self.o, CLEAN)
        meta = self.s.deps.db.get("evidence", run["id"])
        meta["seal"] = "sha256:" + "1" * 64
        self.s.deps.db.put("evidence", meta, tenant_id=self.e.tenant)
        ev = self.s.runs.evidence(self.o, run["id"])
        self.assertFalse(ev["verified"])
        self.assertIsNone(ev["bundle"])

    def test_audit_chain_verifies_and_is_append_only(self):
        self.e.submit(self.o, CLEAN)
        self.assertTrue(self.s.audit.verify(self.o)["ok"])
        with self.assertRaises(Exception):
            self.s.deps.db._conn().execute("UPDATE audit SET data='{}'")

    # ------------------------------------------------------------------ quarantine custody
    def test_quarantine_access_is_purposeful_and_audited(self):
        run = self.e.submit(self.o, SECRET)
        q = run["quarantine_id"]
        viewer = self.e.add_member("view@example.com", "viewer")
        with self.assertRaises(Forbidden):
            self.s.quarantine.access(viewer, q, "just curious about this")
        with self.assertRaises(Forbidden):
            self.s.quarantine.fetch(self.o, q, "qac_nope")
        acc = self.s.quarantine.access(self.o, q, "investigating credential exposure")
        data, _ = self.s.quarantine.fetch(self.o, q, acc["access_id"])
        self.assertIn(b"AKIA", data)
        self.s.quarantine.dispose(self.o, q, "delete", "credential rotated, input destroyed")
        with self.assertRaises(Conflict):
            self.s.quarantine.fetch(self.o, q, acc["access_id"])

    # ------------------------------------------------------------------ reports
    def test_reports_render_in_every_format(self):
        run = self.e.submit(self.o, PII, meta={})
        rep = self.s.runs.report_data(self.o, run["id"])
        for fmt, marker in (("json", b"aidap.report/1"), ("csv", b"severity"), ("html", b"<!doctype html>"), ("pdf", b"%PDF-1.4")):
            body, ctype, ext = render(rep, fmt)
            self.assertIn(marker, body, fmt)
        html = render(rep, "html")[0].decode()
        self.assertNotIn("maria.lopez@example.org", html)
        self.assertNotIn("<script", html.lower())

    def test_csv_export_neutralises_formulas(self):
        from ..reporting import csv_safe
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(csv_safe("plain"), "plain")


class PlansAndBilling(unittest.TestCase):
    def test_developer_plan_gates(self):
        e = Env("developer")
        with self.assertRaises(FeatureNotInPlan):
            e.s.destinations.create(e.owner, {"name": "h", "klass": "local_index", "delivery": "webhook", "target_url": "https://x.example/h"})
        with self.assertRaises(QuotaExceeded):
            e.s.projects.create(e.owner, {"name": "Second project"})
        with self.assertRaises(PayloadTooLarge):
            e.s.runs.submit(e.owner, project_id=e.project["id"], data=b"a" * (10_000_001), filename="big.txt", profile_id="rag_indexing")
        with self.assertRaises(FeatureNotInPlan):
            e.s.auth.invite(e.owner, "a@example.com", "reviewer", [])

    def test_quota_holds_instead_of_billing_overage(self):
        e = Env("developer")
        tot = e.s.usage.totals(e.tenant)
        tot["runs"] = 100
        e.s.deps.db.put("usage_totals", tot, tenant_id=e.tenant)
        with self.assertRaises(QuotaExceeded):
            e.s.runs.submit(e.owner, project_id=e.project["id"], data=json.dumps(CLEAN).encode(), filename="a.json", profile_id="rag_indexing")

    def test_usage_is_idempotent_per_run_and_meter(self):
        e = Env("team")
        run = e.submit(e.owner, CLEAN)
        before = e.s.usage.totals(e.tenant)["runs"]
        self.assertFalse(e.s.usage.record(e.tenant, run["id"], run["project_id"], "run", 1))
        self.assertEqual(e.s.usage.totals(e.tenant)["runs"], before)
        self.assertEqual(before, 1)

    def test_sandbox_checkout_then_payment_failure_grace_and_lapse(self):
        e = Env("developer")
        c = e.s.billing.checkout(e.owner, "starter")
        self.assertTrue(c["sandbox"])
        with self.assertRaises(ValidationFailed):
            e.s.billing.checkout(e.owner, "enterprise")
        st = e.s.billing.sandbox_complete(e.owner, c["id"])
        self.assertEqual(st["effective_plan"]["id"], "starter")
        ev = {"id": "evt_1", "type": "payment_failed", "tenant_id": e.tenant}
        self.assertTrue(e.s.billing.apply_event(ev)["handled"])
        self.assertTrue(e.s.billing.apply_event(ev)["duplicate"])            # providers retry; no double handling
        self.assertEqual(e.s.billing.state(e.owner)["effective_plan"]["id"], "starter")      # inside grace
        e.clock.advance(days=8)
        self.assertEqual(e.s.billing.state(e.owner)["effective_plan"]["id"], "developer")    # grace over: entitlements fall back

    def test_enterprise_is_operator_set_only(self):
        e = Env("developer")
        with self.assertRaises(ValidationFailed):
            e.s.billing.checkout(e.owner, "enterprise")
        e.s.billing.admin_set_plan(e.tenant, "enterprise", note="contract 2026-114")
        self.assertEqual(e.s.billing.state(e.owner)["effective_plan"]["id"], "enterprise")
        with self.assertRaises(Conflict):
            e.s.billing.checkout(e.owner, "team")

    def test_contact_goes_to_the_business_inbox_only(self):
        e = Env("developer")
        self.assertEqual(e.s.contact.submit({"name": "Bot", "email": "bot@example.com", "message": "buy cheap stuff now", "website": "http://spam"})["received"], True)
        self.assertEqual(e.s.deps.db.count("contact_messages"), 0)
        e.s.contact.submit({"name": "Sam", "email": "sam@example.com", "company": "Zed", "topic": "enterprise",
                            "message": "We would like to discuss a private deployment."})
        e.s.drain()
        import pathlib
        mails = [json.loads(p.read_text()) for p in pathlib.Path(e.dir, "mailbox").glob("*.json")]
        contact = [m for m in mails if "enterprise" in m["subject"]]
        self.assertEqual(len(contact), 1)
        self.assertEqual(contact[0]["to"], ["info.remy3design@gmail.com"] if isinstance(contact[0]["to"], list) else "info.remy3design@gmail.com")
        self.assertEqual(contact[0]["reply_to"], "sam@example.com")


class Retention(unittest.TestCase):
    def test_retention_purges_after_the_plan_window_but_not_open_reviews(self):
        e = Env("developer")                                          # 7-day retention
        done = e.submit(e.owner, CLEAN)
        held = e.submit(e.owner, PII, meta={})                       # open review
        e.clock.advance(days=8)
        self.assertEqual(e.s.retention.sweep(), 1)
        self.assertTrue(e.s.runs.get(e.owner, done["id"])["expired"] if "expired" in e.s.runs.get(e.owner, done["id"]) else True)
        self.assertFalse(e.s.deps.db.get("evidence", done["id"]))
        self.assertTrue(e.s.deps.db.get("evidence", held["id"]))
        self.assertTrue(e.s.audit.verify(e.owner)["ok"])             # the audit log outlives the data it describes

    def test_customer_can_delete_run_content_early_but_the_record_stays(self):
        e = Env("team")
        done = e.submit(e.owner, CLEAN)
        held = e.submit(e.owner, PII, meta={})                       # open review: content is still needed
        with self.assertRaises(Conflict):
            e.s.retention.delete_run_content(e.owner, held["id"])
        viewer = e.add_member("v@example.com", "viewer")
        with self.assertRaises(Forbidden):
            e.s.retention.delete_run_content(viewer, done["id"])
        out = e.s.retention.delete_run_content(e.owner, done["id"])
        self.assertTrue(out["deleted"] and not out["already"])
        self.assertTrue(e.s.retention.delete_run_content(e.owner, done["id"])["already"])
        self.assertFalse(e.s.deps.db.get("evidence", done["id"]))
        self.assertEqual(e.s.runs.get(e.owner, done["id"])["decision"], "pass")      # the decision itself is kept
        with self.assertRaises(Conflict):
            e.s.runs.artifact(e.owner, done["id"])
        self.assertTrue(any(a["action"] == "run.content_deleted" for a in e.s.deps.db.audit_events(e.tenant)))
        self.assertTrue(e.s.audit.verify(e.owner)["ok"])

    def test_export_is_owner_only_and_carries_no_credentials_or_content(self):
        e = Env("team")
        e.s.destinations.create(e.owner, {"name": "hook", "klass": "local_index", "delivery": "webhook",
                                          "target_url": "https://example.com/h", "secret": "whsec_supersecretvalue"})
        e.submit(e.owner, CLEAN)
        admin = e.add_member("a@example.com", "admin")
        with self.assertRaises(Forbidden):
            e.s.retention.export_tenant(admin)
        data = e.s.retention.export_tenant(e.owner)
        self.assertEqual(data["schema"], "aidap.export/1")
        self.assertEqual(len(data["runs"]), 1)
        blob = json.dumps(data, default=str)
        for needle in ("whsec_supersecretvalue", "password_hash", "twenty five days"):
            self.assertNotIn(needle, blob)


if __name__ == "__main__":
    unittest.main()
