"""Sandbox billing: no money moves, nothing leaves the machine. Clearly labelled in the API and the UI."""

from __future__ import annotations

import hashlib
from typing import Any

from ...domain.utils.domain_errors import Unavailable
from ...domain.utils.domain_helpers import new_id

__all__ = ["SandboxBilling", "NoBilling"]


class SandboxBilling:
    provider = "sandbox"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        return "cus_sbx_" + hashlib.sha256(tenant_id.encode()).hexdigest()[:14]

    def create_checkout(self, *, tenant_id: str, customer_id: str, plan_id: str, success_url: str, cancel_url: str,
                        idempotency_key: str) -> dict[str, Any]:
        sid = "cs_sbx_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:20]
        return {"id": sid, "url": f"{self.base_url}/app/billing?sandbox_session={sid}&plan={plan_id}",
                "sandbox": True}

    def create_portal(self, customer_id: str, return_url: str) -> str:
        return f"{self.base_url}/app/billing?sandbox_portal=1"

    def cancel_subscription(self, provider_subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]:
        return {"id": provider_subscription_id, "cancel_at_period_end": at_period_end, "sandbox": True}

    def create_topup(self, *, tenant_id: str, customer_id: str, amount_cents: int, success_url: str, cancel_url: str,
                     idempotency_key: str) -> dict[str, Any]:
        sid = "cs_sbx_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:20]
        return {"id": sid, "url": f"{self.base_url}/app/billing?sandbox_session={sid}&topup={amount_cents}",
                "sandbox": True}

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        raise Unavailable("sandbox billing has no external webhooks", code="billing_sandbox")

    def new_subscription_id(self) -> str:
        return new_id("sub_sbx")

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": "sandbox", "detail": "no charges are made"}


class NoBilling:
    """No online billing (self-hosted / contract customers). Plans are set by an operator; checkout is unavailable."""

    provider = "none"

    def _no(self) -> Unavailable:
        return Unavailable("online checkout is not enabled on this deployment; contact sales", code="billing_disabled")

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        return ""

    def create_checkout(self, **_: Any) -> dict[str, Any]:
        raise self._no()

    def create_portal(self, customer_id: str, return_url: str) -> str:
        raise self._no()

    def cancel_subscription(self, provider_subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]:
        raise self._no()

    def create_topup(self, **_: Any) -> dict[str, Any]:
        raise self._no()

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        raise self._no()

    def new_subscription_id(self) -> str:
        return new_id("sub")

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": "none", "detail": "online billing disabled"}
