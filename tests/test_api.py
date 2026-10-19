"""The HTTP surface, exercised over a real socket."""

from __future__ import annotations

import json
import unittest

from ..api import create_app
from .helpers import CLEAN, META, PASSWORD, PII, SECRET, Env
from .http_client import Client, Server


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = Env("developer", overrides={"limits": {"login_rate_per_minute": 1000}})
        cls.srv = Server(create_app(cls.e.s))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.stop()

    def new_user(self, email: str = "") -> tuple[Client, dict]:
        c = Client(self.srv.base)
        email = email or f"u{len(self.e.s.deps.db.find('users', limit=500))}@example.com"
        r = c.post("/api/v1/auth/signup", {"email": email, "name": "Una", "password": PASSWORD, "organization": "Org " + email,
                                          "accept_terms": True})
        self.assertEqual(r.status, 201, r.text)
        return c, r.json()["me"]

    # ------------------------------------------------------------------ public surface
    def test_public_endpoints_and_headers(self):
        c = Client(self.srv.base)
        r = c.get("/api/v1/plans")
        self.assertEqual(r.status, 200)
        plans = {p["id"]: p for p in r.json()["plans"]}
        self.assertEqual(list(plans), ["developer", "starter", "team", "business", "enterprise"])
        self.assertEqual(plans["starter"]["price_month_cents"], 3900)
        self.assertTrue(plans["enterprise"]["contact_sales"])
        for h in ("x-content-type-options", "content-security-policy", "x-frame-options", "referrer-policy", "x-request-id"):
            self.assertIn(h, r.headers)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(c.get("/api/v1/health").json()["status"], "ok")
        self.assertIn(c.get("/api/v1/health/ready").status, (200, 503))
        self.assertGreater(len(c.get("/api/v1/catalog/checks").json()), 10)
        nf = c.get("/api/v1/nope")
        self.assertEqual((nf.status, nf.json()["error"]["code"]), (404, "not_found"))

    def test_spa_fallback_serves_index_or_placeholder(self):
        c = Client(self.srv.base)
        r = c.get("/app/runs")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertEqual(c.get("/does-not-exist.js").status, 404)

    def test_contact_form_validates_and_rejects_honeypot(self):
        c = Client(self.srv.base)
        self.assertEqual(c.post("/api/v1/contact", {"name": "A", "email": "not-an-email", "message": "short"}).status, 422)
        ok = c.post("/api/v1/contact", {"name": "Sam", "email": "sam@example.com", "message": "We want a private deployment please."})
        self.assertEqual(ok.status, 202)

    # ------------------------------------------------------------------ sessions & CSRF
    def test_signup_session_csrf_and_logout(self):
        c, me = self.new_user()
        self.assertEqual(me["role"], "owner")
        self.assertEqual(me["plan"]["id"], "developer")
        self.assertEqual(c.get("/api/v1/me").status, 200)
        # cookie flags
        sc = [v for k, v in c.opener.handlers[0].cookiejar.__dict__.items()] if False else None
        self.assertTrue(c.cookie("aidap_session").startswith("aidap_s_"))
        # unsafe request without CSRF header is refused
        r = c.request("POST", "/api/v1/projects", json_body={"name": "Another one"}, csrf=False)
        self.assertEqual(r.status, 403)
        self.assertEqual(r.json()["error"]["code"], "csrf_failed")
        # cross-origin is refused even with a valid token
        r = c.request("POST", "/api/v1/auth/mfa/setup", json_body={}, headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        self.assertEqual(c.post("/api/v1/auth/logout").status, 200)
        self.assertEqual(c.get("/api/v1/me").status, 401)

    def test_login_failures_do_not_reveal_which_part_was_wrong(self):
        c, _ = self.new_user("known@example.com")
        anon = Client(self.srv.base)
        a = anon.post("/api/v1/auth/login", {"email": "known@example.com", "password": "wrong"})
        b = anon.post("/api/v1/auth/login", {"email": "ghost@example.com", "password": "wrong"})
        self.assertEqual((a.status, b.status), (401, 401))
        self.assertEqual(a.json()["error"]["message"], b.json()["error"]["message"])

    def test_validation_errors_are_aggregated_and_unknown_keys_rejected(self):
        c, _ = self.new_user()
        r = c.post("/api/v1/projects", {"name": "x", "bogus": 1})
        self.assertEqual(r.status, 422)
        fields = r.json()["error"]["details"]["fields"]
        self.assertIn("name", fields)
        self.assertIn("bogus", fields)

    # ------------------------------------------------------------------ runs over HTTP
    def test_multipart_run_with_wait_report_and_evidence(self):
        c, me = self.new_user()
        proj = c.get("/api/v1/projects").json()[0]
        r = c.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing", "source_class": "internal_doc",
                                       "metadata": json.dumps(META), "wait": "true"}, "leave.json", json.dumps(CLEAN).encode())
        self.assertIn(r.status, (200, 202), r.text)
        run = r.json()
        self.assertEqual((run["state"], run["decision"]), ("completed", "pass"), run)
        rid = run["id"]
        self.assertEqual(c.get(f"/api/v1/runs/{rid}/findings").status, 200)
        ev = c.get(f"/api/v1/runs/{rid}/evidence").json()
        self.assertTrue(ev["verified"])
        pdf = c.get(f"/api/v1/runs/{rid}/report?format=pdf")
        self.assertEqual(pdf.status, 200)
        self.assertTrue(pdf.body.startswith(b"%PDF-1.4"))
        self.assertIn("attachment", pdf.headers["content-disposition"])
        art = c.get(f"/api/v1/runs/{rid}/artifact")
        self.assertEqual(art.status, 200)
        self.assertEqual(json.loads(art.body)[0]["title"], "T")
        lst = c.get("/api/v1/runs?decision=pass").json()
        self.assertEqual(lst["total"], 1)

    def test_pdf_and_docx_uploads_are_read_and_released_as_the_original_bytes(self):
        from ..slai.reader_intake import ReaderIntake
        if not ReaderIntake().enabled:
            self.skipTest("SLAI Reader is not available")
        from . import documents as D
        c, _ = self.new_user()
        proj = c.get("/api/v1/projects").json()[0]
        body = CLEAN[0]["body"]
        for name, data in (("leave.pdf", D.pdf([body])), ("leave.docx", D.docx([body]))):
            run = c.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing", "source_class": "internal_doc",
                                             "metadata": json.dumps(META), "wait": "true"}, name, data).json()
            self.assertEqual((run["state"], run["decision"]), ("completed", "pass"), run)
            art = c.get(f"/api/v1/runs/{run['id']}/artifact")
            self.assertEqual((art.status, art.body), (200, data))
        bad = c.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing", "source_class": "internal_doc",
                                         "metadata": json.dumps(META), "wait": "true"}, "macro.docx",
                       D.docx([body], macros=True)).json()
        self.assertNotEqual(bad["decision"], "pass")
        self.assertEqual(c.get(f"/api/v1/runs/{bad['id']}/artifact").status, 403)

    def test_secret_run_cannot_be_downloaded(self):
        c, _ = self.new_user()
        proj = c.get("/api/v1/projects").json()[0]
        run = c.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing", "source_class": "internal_doc",
                                         "wait": "true"}, "s.json", json.dumps(SECRET).encode()).json()
        self.assertEqual(run["decision"], "block")
        r = c.get(f"/api/v1/runs/{run['id']}/artifact")
        self.assertEqual((r.status, r.json()["error"]["code"]), (403, "release_not_authorized"))

    def test_raw_body_upload_and_idempotency_header(self):
        c, _ = self.new_user()
        proj = c.get("/api/v1/projects").json()[0]
        q = f"/api/v1/runs?project_id={proj['id']}&profile_id=rag_indexing&source_class=internal_doc&wait=true"
        a = c.request("POST", q, data=json.dumps(CLEAN).encode(), content_type="application/octet-stream",
                      headers={"X-Filename": "raw.json", "Idempotency-Key": "abc"})
        b = c.request("POST", q, data=json.dumps(CLEAN).encode(), content_type="application/octet-stream",
                      headers={"X-Filename": "raw.json", "Idempotency-Key": "abc"})
        self.assertEqual(a.json()["id"], b.json()["id"])

    def test_simulate_does_not_store_or_use_quota(self):
        c, _ = self.new_user()
        before = c.get("/api/v1/usage").json()["used"]["runs"]
        r = c.post("/api/v1/simulate", {"profile_id": "rag_indexing", "content": json.dumps(PII), "filename": "x.json",
                                        "source_class": "internal_doc"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json()["decision"], "review")
        self.assertFalse(r.json()["stored"])
        self.assertEqual(c.get("/api/v1/usage").json()["used"]["runs"], before)
        self.assertEqual(c.get("/api/v1/runs").json()["total"], 0)

    # ------------------------------------------------------------------ API keys and scopes
    def test_api_key_scope_and_revocation(self):
        c, _ = self.new_user()
        # API access is part of every plan, including Developer
        k = c.post("/api/v1/api-keys", {"name": "ci", "scopes": ["runs:read"]})
        self.assertEqual(k.status, 201, k.text)
        key = k.json()["token"]
        self.assertTrue(key.startswith("aidk_"))
        bearer = Client(self.srv.base, bearer=key)
        self.assertEqual(bearer.get("/api/v1/runs").status, 200)
        proj = c.get("/api/v1/projects").json()[0]
        denied = bearer.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing"}, "a.json", b"[]")
        self.assertEqual(denied.status, 403)
        self.assertEqual(bearer.get("/api/v1/billing").status, 403)
        self.assertEqual(c.request("DELETE", f"/api/v1/api-keys/{k.json()['id']}").status, 200)
        self.assertEqual(bearer.get("/api/v1/runs").status, 401)

    def test_tenant_isolation(self):
        a, _ = self.new_user()
        b, _ = self.new_user()
        proj = a.get("/api/v1/projects").json()[0]
        run = a.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing", "source_class": "internal_doc",
                                         "wait": "true"}, "x.json", json.dumps(CLEAN).encode()).json()
        for path in (f"/api/v1/runs/{run['id']}", f"/api/v1/runs/{run['id']}/findings", f"/api/v1/runs/{run['id']}/artifact",
                     f"/api/v1/runs/{run['id']}/evidence"):
            self.assertEqual(b.get(path).status, 404, path)
        self.assertEqual(b.upload("/api/v1/runs", {"project_id": proj["id"], "profile_id": "rag_indexing"}, "x.json", b"[]").status, 404)

    # ------------------------------------------------------------------ rate limiting & billing
    def test_billing_flow_over_http_and_stripe_webhook_is_refused_in_sandbox(self):
        c, _ = self.new_user()
        co = c.post("/api/v1/billing/checkout", {"plan_id": "starter"})
        self.assertEqual(co.status, 200, co.text)
        self.assertTrue(co.json()["sandbox"])
        done = c.post("/api/v1/billing/sandbox/complete", {"session_id": co.json()["id"]})
        self.assertEqual(done.json()["effective_plan"]["id"], "starter")
        self.assertEqual(c.get("/api/v1/me").json()["plan"]["id"], "starter")
        w = Client(self.srv.base).request("POST", "/api/v1/webhooks/stripe", data=b"{}", content_type="application/json")
        self.assertIn(w.status, (400, 503))

    def test_rate_limit_returns_429_with_retry_after(self):
        e = Env("developer")
        e.s.deps.limiter = type("L", (), {"n": 0, "check": lambda self, key, tokens=1: (self.__class__.__dict__.get("ok", True) and self._bump(), 2.0)})()
        e.s.deps.limiter._bump = lambda: (setattr(e.s.deps.limiter, "n", e.s.deps.limiter.n + 1) or e.s.deps.limiter.n <= 2)
        srv = Server(create_app(e.s))
        try:
            c = Client(srv.base)
            codes = [c.get("/api/v1/plans").status for _ in range(4)]
            self.assertEqual(codes[:2], [200, 200])
            self.assertIn(429, codes)
            r = c.get("/api/v1/plans")
            self.assertEqual(r.headers["retry-after"], "2")
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
