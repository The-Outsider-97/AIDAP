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
