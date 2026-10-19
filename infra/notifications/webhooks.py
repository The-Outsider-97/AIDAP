"""Outbound webhooks through SLAI's ``WebhookService`` (HMAC-signed, SSRF-guarded, no redirects, bounded)."""

from __future__ import annotations

from typing import Any

from ...app.ports import WebhookResult
from ...slai.runtime import functions

__all__ = ["SlaiWebhookSender"]


class SlaiWebhookSender:
    def __init__(self, *, allow_http: bool = False, allow_private_hosts: bool = False, timeout: float = 10.0) -> None:
        self.mod = functions("webhook")
        self.allow_http = allow_http
        self.allow_private_hosts = allow_private_hosts
        self.timeout = timeout

    def validate_target(self, url: str) -> None:
        """Syntax + SSRF validation without sending anything (used when a destination is saved)."""
        svc = self.mod.WebhookService(url, "x" * 32, allow_http=self.allow_http,
                                      allow_private_hosts=self.allow_private_hosts)
        try:
            self.mod._assert_safe_destination(svc._parsed_endpoint, allow_private_hosts=self.allow_private_hosts)
        finally:
            svc.close()

    def send(self, url: str, secret: str, event_id: str, payload: dict[str, Any]) -> WebhookResult:
        m = self.mod
        try:
            svc = m.WebhookService(url, secret, allow_http=self.allow_http, allow_private_hosts=self.allow_private_hosts,
                                   timeout_seconds=self.timeout, retry_policy=m.WebhookRetryPolicy(max_retries=1,
                                                                                                    base_delay=0.2,
                                                                                                    max_delay=1.0))
        except m.WebhookError as exc:
            return WebhookResult(False, None, False, f"{type(exc).__name__}: {exc}"[:300])
        try:
            res = svc.send(str(payload.get("type", "aidap.event")), payload, event_id=event_id)
            return WebhookResult(True, res.status_code, False, "", res.attempts)
        except m.WebhookDeliveryError as exc:
            return WebhookResult(False, getattr(exc, "status_code", None), bool(getattr(exc, "retryable", False)),
                                 f"{type(exc).__name__}: {exc}"[:300])
        except m.WebhookError as exc:                                  # security / configuration: never retried
            return WebhookResult(False, None, False, f"{type(exc).__name__}: {exc}"[:300])
        finally:
            svc.close()
