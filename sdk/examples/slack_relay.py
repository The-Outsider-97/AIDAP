"""Forward AIDAP decision webhooks to a Slack incoming webhook.

AIDAP signs its webhooks (SLAI webhook envelope), and Slack accepts only its own JSON shape, so a small relay in your own
infrastructure verifies the signature and reposts. Run it behind HTTPS and point an AIDAP webhook destination at it.
"""
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from aidap_sdk import SignatureError, verify_signature

SECRET = os.environ["AIDAP_WEBHOOK_SECRET"]
SLACK = os.environ["SLACK_WEBHOOK_URL"]


class Relay(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            verify_signature(SECRET, body, dict(self.headers))
        except SignatureError:
            self.send_response(401); self.end_headers(); return
        event = json.loads(body)
        d = event.get("data", event)
        if d.get("decision") != "pass":
            text = f":warning: AIDAP {d.get('decision', '').upper()} for run {d.get('run_id')}: {', '.join(d.get('reason_codes', []))[:300]}"
            req = urllib.request.Request(SLACK, json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        self.send_response(204); self.end_headers()


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8081"))), Relay).serve_forever()
