"""E-mail through SLAI's ``EmailService`` (SMTP in production; a file mailbox for development and tests)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ...domain.utils.domain_helpers import iso, new_id, utcnow
from ...slai.runtime import functions

__all__ = ["SlaiMailer", "build_mailer"]


class SlaiMailer:
    def __init__(self, service: Any, default_from: str, backend_name: str) -> None:
        self.service = service
        self.default_from = default_from
        self.backend_name = backend_name

    def send(self, to: str, subject: str, text: str, *, html: str = "", reply_to: str = "") -> None:
        if not re.fullmatch(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+", to):
            raise ValueError("invalid recipient")
        self.service.send(to=to, subject=subject[:200].replace("\n", " "),
                          body_html=html or "<pre>" + _esc(text) + "</pre>", body_text=text,
                          from_addr=self.default_from, reply_to=reply_to or None)

    def health(self) -> dict[str, Any]:
        try:
            ok = bool(self.service.backend.test_connection())
        except Exception as exc:                                       # noqa: BLE001
            return {"ok": False, "backend": self.backend_name, "error": str(exc)[:200]}
        return {"ok": ok, "backend": self.backend_name}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_mailer(*, mailbox_dir: Path, default_from: str, smtp: dict[str, Any] | None) -> SlaiMailer:
    em = functions("email")
    if smtp and smtp.get("host"):
        backend = em.SMTPBackend(host=smtp["host"], port=int(smtp.get("port", 587)), username=smtp.get("user") or None,
                                 password=smtp.get("password") or None, use_tls=bool(smtp.get("tls", True)),
                                 use_ssl=bool(smtp.get("ssl", False)), default_from=default_from)
        name = "smtp"
    else:
        class FileMailbox(em.EmailBackend):                             # type: ignore[misc, name-defined]
            """Development backend: every message is written as JSON; nothing leaves the machine."""

            def send(self, message: Any) -> None:
                mailbox_dir.mkdir(parents=True, exist_ok=True)
                doc = {"id": new_id("mail"), "at": iso(utcnow()), "to": message.to, "subject": message.subject,
                       "text": message.body_text, "html": message.body_html, "reply_to": message.reply_to}
                (mailbox_dir / f"{doc['id']}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

            def test_connection(self) -> bool:
                return True

            def close(self) -> None:
                return None

        backend = FileMailbox()
        name = "file-mailbox"
    service = em.EmailService(backend, async_send=False, retry_policy=em.EmailRetryPolicy(max_retries=1, base_delay=0.2,
                                                                                             max_delay=1.0))
    return SlaiMailer(service, default_from, name)
