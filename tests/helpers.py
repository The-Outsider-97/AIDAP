"""Shared test fixtures: a real bootstrapped AIDAP (SQLite, real adapters) with only the network-facing ports faked."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from ..app.ports import WebhookResult
from ..bootstrap import bootstrap

PASSWORD = "Correct-Horse-Battery-42!"
META = {"owner": "HR Team", "source_revision": "3", "effective_date": "2026-09-01"}


class FakeWebhooks:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_next = 0

    def validate_target(self, url: str) -> None:
        if not url.startswith("https://"):
            raise ValueError("webhook targets must use https")

    def send(self, url: str, secret: str, event_id: str, payload: dict[str, Any]) -> WebhookResult:
        if self.fail_next:
            self.fail_next -= 1
            return WebhookResult(False, 503, True, "upstream unavailable")
        self.sent.append({"url": url, "secret": secret, "event_id": event_id, "payload": payload})
        return WebhookResult(True, 200)


class MutableClock:
    def __init__(self) -> None:
        self.t = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw: Any) -> None:
        self.t += timedelta(**kw)


class Env:
    def __init__(self, plan: str = "team", **bootstrap_kw: Any) -> None:
        self.dir = tempfile.mkdtemp(prefix="aidap-test-")
        self.webhooks = FakeWebhooks()
        self.clock = MutableClock()
        self.s = bootstrap(data_dir=self.dir, env={}, deps_overrides={"webhooks": self.webhooks, "clock": self.clock}, **bootstrap_kw)
        r = self.s.auth.signup(email="owner@example.com", name="Olivia Owner", password=PASSWORD, organization="Acme",
                               accept_terms=True, ip="10.0.0.1")
        self.owner = r["principal"]
        self.tenant = self.owner.tenant_id
        if plan != "developer":
            self.s.billing.admin_set_plan(self.tenant, plan, note="test")
        self.project = self.s.projects.list(self.owner)[0]

    def add_member(self, email: str, role: str):
        inv = self.s.auth.invite(self.owner, email, role, [])
        r = self.s.auth.accept_invitation(inv["token"], role.title(), PASSWORD, ip="10.0.0.2")
        return r["principal"]

    def submit(self, p, payload: Any, name: str = "doc.json", *, meta: dict | None = None, profile: str = "rag_indexing", **kw: Any):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        run = self.s.runs.submit(p, project_id=self.project["id"], data=data, filename=name, profile_id=profile,
                                 metadata=META if meta is None else meta, source_class=kw.pop("source_class", "internal_doc"), **kw)
        self.s.drain()
        return self.s.runs.get(p, run["id"])


def doc(body: str, **extra: Any) -> list[dict[str, Any]]:
    return [{"title": "T", "body": body, **extra}]


CLEAN = doc("Employees accrue twenty five days of paid leave per calendar year and may carry over five days into the next year.")
PII = doc("Contact Maria at maria.lopez@example.org or +34 612 345 678 for the onboarding materials and forms for new staff.")
SECRET = doc("Deploy with the key AKIAIOSFODNN7EXAMPLE and the service account password for the production database cluster.")
