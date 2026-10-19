"""Transactional e-mail through an idempotent outbox (survives crashes; one event is sent once per dedupe key)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...domain.reports.models import OutboxEvent
from ...domain.utils.domain_helpers import iso, new_id, parse_iso

__all__ = ["NotificationService"]

MAX_ATTEMPTS = 5


class NotificationService:
    def __init__(self, deps: Any) -> None:
        self.d = deps

    def email(self, tenant_id: str, to: str, subject: str, text: str, *, html: str = "", reply_to: str = "",
              dedupe_key: str = "") -> str:
        ev = OutboxEvent(new_id("obx"), tenant_id, "email",
                         {"to": to, "subject": subject, "text": text, "html": html, "reply_to": reply_to},
                         self.d.now(), next_attempt_at=self.d.now(), dedupe_key=dedupe_key)
        doc = ev.to_dict()
        if not self.d.db.insert("outbox", doc, tenant_id=tenant_id, ukey=f"{tenant_id}:{dedupe_key}" if dedupe_key else None):
            existing = self.d.db.get_by_ukey("outbox", f"{tenant_id}:{dedupe_key}")
            return existing["id"] if existing else doc["id"]
        self.d.queue.enqueue("outbox", {"id": doc["id"]}, dedupe_key=f"outbox:{doc['id']}", max_attempts=1)
        return doc["id"]

    def process(self, event_id: str) -> str:
        ev = self.d.db.get("outbox", event_id)
        if ev is None or ev["state"] in ("sent", "dead"):
            return "skipped"
        try:
            if ev["kind"] != "email":
                raise ValueError(f"unknown outbox kind {ev['kind']}")
            pl = ev["payload"]
            self.d.mailer.send(pl["to"], pl["subject"], pl["text"], html=pl.get("html", ""), reply_to=pl.get("reply_to", ""))
        except Exception as exc:                                    # noqa: BLE001 - mail failures are retried, not fatal
            ev["attempts"] += 1
            ev["last_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            if ev["attempts"] >= MAX_ATTEMPTS:
                ev["state"] = "dead"
            else:
                ev["state"] = "failed"
                delay = min(3600, 30 * 2 ** ev["attempts"])
                ev["next_attempt_at"] = iso(self.d.now() + timedelta(seconds=delay))
                self.d.queue.enqueue("outbox", {"id": event_id}, dedupe_key=f"outbox:{event_id}:{ev['attempts']}",
                                     run_after=self.d.now() + timedelta(seconds=delay), max_attempts=1)
            self.d.db.put("outbox", ev, tenant_id=ev["tenant_id"])
            return ev["state"]
        ev["state"] = "sent"
        ev["attempts"] += 1
        self.d.db.put("outbox", ev, tenant_id=ev["tenant_id"])
        return "sent"

    def sweep(self) -> int:
        """Re-enqueue any pending/failed event whose time has come (covers a lost queue row)."""
        n = 0
        for ev in self.d.db.find("outbox", where={"state": ["pending", "failed"]}, limit=200, desc=False):
            due = parse_iso(ev.get("next_attempt_at")) or self.d.now()
            if due <= self.d.now():
                self.d.queue.enqueue("outbox", {"id": ev["id"]}, dedupe_key=f"outbox:{ev['id']}:sweep", max_attempts=1)
                n += 1
        return n
