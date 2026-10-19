from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk"))

from aidap_sdk import AidapError, Client, SignatureError, verify_signature          # noqa: E402
from aidap_sdk.__main__ import main as sdk_main                                      # noqa: E402

from ..api import create_app                                                          # noqa: E402
from .helpers import CLEAN, META, PASSWORD, SECRET, Env                              # noqa: E402
from .http_client import Client as Http, Server                                      # noqa: E402


class Sdk(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = Env("developer", overrides={"limits": {"login_rate_per_minute": 1000}})
        cls.srv = Server(create_app(cls.e.s))
        h = Http(cls.srv.base)
        h.post("/api/v1/auth/signup", {"email": "sdk@example.com", "name": "S", "password": PASSWORD, "organization": "SDK Co", "accept_terms": True})
        cls.project = h.get("/api/v1/projects").json()[0]["id"]
        cls.key = h.post("/api/v1/api-keys", {"name": "sdk", "scopes": ["runs:write", "runs:read"]}).json()["token"]
        cls.client = Client(cls.srv.base, cls.key)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.stop()

    def test_assure_pass_then_download(self):
        r = self.client.assure(json.dumps(CLEAN), project=self.project, profile="rag_indexing", filename="leave.json",
                               source_class="internal_doc", metadata=META)
        self.assertEqual((r.decision, r.release_authorized), ("pass", True))
        self.assertEqual(json.loads(self.client.artifact(r.run_id))[0]["title"], "T")
        self.assertIn(b"aidap.report/1", self.client.report(r.run_id, "json"))
        self.assertTrue(self.client.evidence(r.run_id)["verified"])

    def test_assure_block_refuses_download(self):
        r = self.client.assure(json.dumps(SECRET), project=self.project, profile="rag_indexing", filename="s.json", source_class="internal_doc")
        self.assertEqual((r.decision, r.release_authorized), ("block", False))
        self.assertTrue(any(c.startswith("privacy.secret") for c in r.reason_codes))
        with self.assertRaises(AidapError) as cm:
            self.client.artifact(r.run_id)
        self.assertEqual(cm.exception.code, "release_not_authorized")

    def test_cli_exit_codes(self):
        p = Path(self.e.dir) / "in.json"
        p.write_text(json.dumps(SECRET))
        self.assertEqual(sdk_main(["check", str(p), "--project", self.project, "--profile", "rag_indexing", "--source-class", "internal_doc",
                                   "--url", self.srv.base, "--api-key", self.key]), 30)
        p.write_text(json.dumps(CLEAN))
        self.assertEqual(sdk_main(["check", str(p), "--project", self.project, "--profile", "rag_indexing", "--source-class", "internal_doc",
                                   "--metadata", json.dumps(META), "--url", self.srv.base, "--api-key", self.key]), 0)

    def test_idempotent_submit(self):
        a = self.client.submit(json.dumps(CLEAN), project=self.project, profile="rag_indexing", idempotency_key="same", metadata=META)
        b = self.client.submit(json.dumps(CLEAN), project=self.project, profile="rag_indexing", idempotency_key="same", metadata=META)
        self.assertEqual(a["id"], b["id"])


class SdkExtras(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = Env("team", overrides={"limits": {"login_rate_per_minute": 1000}})
        cls.srv = Server(create_app(cls.e.s))
        cls.h = Http(cls.srv.base)
        assert cls.h.post("/api/v1/auth/login", {"email": "owner@example.com", "password": PASSWORD}).status == 200
        cls.project = cls.h.get("/api/v1/projects").json()[0]["id"]
        cls.key = cls.h.post("/api/v1/api-keys", {"name": "ci", "scopes": ["runs:write", "runs:read", "policies:read"]}).json()["token"]
        cls.client = Client(cls.srv.base, cls.key)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.stop()

    def check(self, *extra: str) -> int:
        p = Path(self.e.dir) / "in.json"
        p.write_text(json.dumps(CLEAN))
        return sdk_main(["check", str(p), "--project", self.project, "--profile", "rag_indexing", "--source-class", "internal_doc",
                         "--metadata", json.dumps(META), "--url", self.srv.base, "--api-key", self.key, *extra])

    def test_upstream_results_are_passed_on_and_a_failure_withholds_the_pass(self):
        self.assertEqual(self.check("--upstream", "soda:orders=passed"), 0)
        self.assertEqual(self.check("--upstream", "monte_carlo:orders_freshness=failed"), 10)
        gx = Path(self.e.dir) / "gx.json"
        gx.write_text(json.dumps({"success": False, "statistics": {"evaluated_expectations": 4, "unsuccessful_expectations": 1},
                                  "meta": {"expectation_suite_name": "orders"}}))
        self.assertEqual(self.check("--gx-result", str(gx)), 10)
        self.assertEqual(self.check("--upstream", "broken"), 2)

    def test_github_annotations_and_step_summary(self):
        import io, os, contextlib
        summary = Path(self.e.dir) / "summary.md"
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.check("--upstream", "monte_carlo:orders=failed", "--github")
        finally:
            del os.environ["GITHUB_STEP_SUMMARY"]
        self.assertIn("::warning title=AIDAP REVIEW::", buf.getvalue())
        self.assertIn("provenance.upstream.failed", buf.getvalue())
        self.assertIn("provenance.upstream.failed", summary.read_text())

    def test_suite_command_exit_codes(self):
        su = self.h.post("/api/v1/suites", {"name": "ci"}).json()
        for exp, payload in (("pass", CLEAN), ("block", SECRET)):
            self.h.post(f"/api/v1/suites/{su['id']}/cases", {"expected": exp, "name": exp, "filename": "d.json",
                                                             "source_class": "internal_doc", "metadata": META, "content": json.dumps(payload)})
        args = ["suite", su["id"], "--profile", "rag_indexing", "--url", self.srv.base, "--api-key", self.key]
        self.assertEqual(sdk_main(args), 0)
        self.h.post(f"/api/v1/suites/{su['id']}/cases", {"expected": "pass", "name": "wrong", "filename": "d.json",
                                                         "source_class": "internal_doc", "content": json.dumps(SECRET)})
        self.assertEqual(sdk_main(args), 1)
        self.assertIn("review", self.client.insights(7))

    def test_mcp_tools_check_content_and_never_return_it(self):
        import os
        from aidap_sdk import mcp
        os.environ["AIDAP_PROJECT"], os.environ["AIDAP_PROFILE"] = self.project, "rag_indexing"
        try:
            out = mcp.call_tool(self.client, "aidap_check", {"text": json.dumps(SECRET), "source_class": "internal_doc"})
        finally:
            del os.environ["AIDAP_PROJECT"], os.environ["AIDAP_PROFILE"]
        body = json.loads(out["content"][0]["text"])
        self.assertEqual((body["decision"], body["usable"]), ("block", False))
        self.assertNotIn("AKIA", out["content"][0]["text"])
        f = mcp.call_tool(self.client, "aidap_findings", {"run_id": body["run_id"]})
        self.assertNotIn("AKIA", f["content"][0]["text"])
        self.assertTrue(mcp.call_tool(self.client, "nope", {})["isError"])
        self.assertEqual({t["name"] for t in mcp.TOOLS}, {"aidap_check", "aidap_result", "aidap_findings"})

    def test_mcp_stdio_handshake(self):
        import io, contextlib
        from aidap_sdk import mcp
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 3, "method": "bogus"}]
        old_in = sys.stdin
        sys.stdin = io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                mcp.serve(self.client)
        finally:
            sys.stdin = old_in
        out = [json.loads(x) for x in buf.getvalue().splitlines()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3])
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "aidap")
        self.assertEqual(len(out[1]["result"]["tools"]), 3)
        self.assertEqual(out[2]["error"]["code"], -32601)


class WebhookSignatures(unittest.TestCase):
    secret = "whsec_" + "x" * 43

    def sign(self, body: bytes, ts: int, eid: str) -> str:
        return "v1=" + hmac.new(self.secret.encode(), f"{ts}.{eid}.".encode() + body, hashlib.sha256).hexdigest()

    def test_verify_roundtrip_and_tamper(self):
        body, ts = b'{"decision":"pass"}', int(time.time())
        hdr = {"X-SLAI-Webhook-Id": "evt_1", "X-SLAI-Webhook-Timestamp": str(ts), "X-SLAI-Webhook-Signature": self.sign(body, ts, "evt_1")}
        verify_signature(self.secret, body, hdr)
        with self.assertRaises(SignatureError):
            verify_signature(self.secret, b'{"decision":"block"}', hdr)
        with self.assertRaises(SignatureError):
            verify_signature(self.secret, body, hdr, now=ts + 10_000)           # replay window

    def test_matches_slai_signing_implementation(self):
        from ..slai.runtime import functions
        wh = functions("webhook")
        body, ts = b'{"a":1}', int(time.time())
        sig = wh.sign_webhook_payload(self.secret, body=body, timestamp=ts, event_id="evt_9") if hasattr(wh, "sign_webhook_payload") else None
        if sig is None:
            self.skipTest("signing helper has a different name in this SLAI version")
        verify_signature(self.secret, body, {"X-SLAI-Webhook-Id": "evt_9", "X-SLAI-Webhook-Timestamp": str(ts), "X-SLAI-Webhook-Signature": sig})


if __name__ == "__main__":
    unittest.main()
