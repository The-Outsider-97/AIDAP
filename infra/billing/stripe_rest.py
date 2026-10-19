"""Stripe over its REST API (no SDK dependency).

Prices are *Stripe Price ids supplied through the environment* (``AIDAP_STRIPE_PRICE_<PLAN>``); AIDAP never invents
or hard-codes a live price. Webhooks are authenticated with Stripe's documented ``t=...,v1=...`` HMAC scheme and a
timestamp tolerance. NOTE: this adapter is unit-tested against recorded payload shapes and signatures; it has not been
exercised against a live Stripe account.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlencode

from ...domain.utils.domain_errors import Unavailable, ValidationFailed

__all__ = ["StripeBilling"]

Transport = Callable[[str, str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]
API = "https://api.stripe.com"


def flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out += flatten(v, key)
        elif isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                out += flatten(item, f"{key}[{i}]") if isinstance(item, dict) else [(f"{key}[{i}]", str(item))]
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


def _urllib_transport(method: str, path: str, form: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    body = urlencode(flatten(form)).encode() if form and method != "GET" else None
    url = API + path + (("?" + urlencode(flatten(form))) if form and method == "GET" else "")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:                   # noqa: S310 - fixed https host
            return resp.status, json.loads(resp.read(2_000_000) or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(200_000) or b"{}")
        except ValueError:
            return exc.code, {}
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Unavailable(f"payment provider unreachable: {type(exc).__name__}", code="billing_unreachable") from exc


class StripeBilling:
    provider = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str, price_ids: dict[str, str], *,
                 transport: Transport | None = None, tolerance: int = 300) -> None:
        if not secret_key.startswith(("sk_", "rk_")):
            raise Unavailable("AIDAP_STRIPE_SECRET_KEY does not look like a Stripe secret key", code="config_error")
        self._key, self._whsec, self.price_ids, self.tolerance = secret_key, webhook_secret, price_ids, tolerance
        self._transport = transport or _urllib_transport
        self._plan_by_price = {v: k for k, v in price_ids.items() if v}

    # ------------------------------------------------------------------ requests
    def _call(self, method: str, path: str, form: dict[str, Any] | None = None, *, idem: str = "") -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/x-www-form-urlencoded",
                   "Stripe-Version": "2024-06-20"}
        if idem:
            headers["Idempotency-Key"] = idem[:255]
        status, body = self._transport(method, path, form or {}, headers)
        if status >= 400:
            msg = (body.get("error") or {}).get("message", f"HTTP {status}")
            raise Unavailable(f"payment provider error: {msg}"[:300], code="billing_provider_error",
                              details={"status": status})
        return body

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        res = self._call("POST", "/v1/customers", {"email": email, "name": name, "metadata": {"tenant_id": tenant_id}},
                         idem=f"cust-{tenant_id}")
        return str(res["id"])

    def create_checkout(self, *, tenant_id: str, customer_id: str, plan_id: str, success_url: str, cancel_url: str,
                        idempotency_key: str) -> dict[str, Any]:
        price = self.price_ids.get(plan_id)
        if not price:
            raise ValidationFailed(f"no Stripe price is configured for plan '{plan_id}'", code="price_not_configured")
        res = self._call("POST", "/v1/checkout/sessions", {
            "mode": "subscription", "customer": customer_id, "client_reference_id": tenant_id,
            "line_items": [{"price": price, "quantity": 1}], "success_url": success_url, "cancel_url": cancel_url,
            "metadata": {"tenant_id": tenant_id, "plan_id": plan_id},
            "subscription_data": {"metadata": {"tenant_id": tenant_id, "plan_id": plan_id}},
            "allow_promotion_codes": True, "billing_address_collection": "required",
            "tax_id_collection": {"enabled": True}}, idem=idempotency_key)
        return {"id": res["id"], "url": res["url"]}

    def create_portal(self, customer_id: str, return_url: str) -> str:
        res = self._call("POST", "/v1/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})
        return str(res["url"])

    def cancel_subscription(self, provider_subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]:
        if at_period_end:
            return self._call("POST", f"/v1/subscriptions/{provider_subscription_id}", {"cancel_at_period_end": True})
        return self._call("DELETE", f"/v1/subscriptions/{provider_subscription_id}")

    def create_topup(self, *, tenant_id: str, customer_id: str, amount_cents: int, success_url: str, cancel_url: str,
                     idempotency_key: str) -> dict[str, Any]:
        res = self._call("POST", "/v1/checkout/sessions", {
            "mode": "payment", "customer": customer_id, "client_reference_id": tenant_id,
            "line_items": [{"quantity": 1, "price_data": {"currency": "eur", "unit_amount": amount_cents,
                                                          "product_data": {"name": "AIDAP managed-inference top-up"}}}],
            "success_url": success_url, "cancel_url": cancel_url,
            "metadata": {"tenant_id": tenant_id, "kind": "topup", "amount_cents": amount_cents}}, idem=idempotency_key)
        return {"id": res["id"], "url": res["url"]}

    # ------------------------------------------------------------------ webhooks
    def verify_signature(self, payload: bytes, header: str, *, now: float | None = None) -> None:
        if not self._whsec:
            raise Unavailable("AIDAP_STRIPE_WEBHOOK_SECRET is not configured", code="config_error")
        items = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
        ts = items.get("t", "")
        sigs = [v for k, v in (p.split("=", 1) for p in (header or "").split(",") if "=" in p) if k == "v1"]
        if not ts.isdigit() or not sigs:
            raise ValidationFailed("malformed signature header", code="bad_signature")
        if abs((now if now is not None else time.time()) - int(ts)) > self.tolerance:
            raise ValidationFailed("signature timestamp outside tolerance", code="bad_signature")
        expected = hmac.new(self._whsec.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, s) for s in sigs):
            raise ValidationFailed("signature mismatch", code="bad_signature")

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        self.verify_signature(payload, signature)
        try:
            evt = json.loads(payload)
        except ValueError as exc:
            raise ValidationFailed("webhook body is not JSON", code="bad_payload") from exc
        return self.normalise(evt)

    def normalise(self, evt: dict[str, Any]) -> dict[str, Any]:
        et, obj = str(evt.get("type", "")), (evt.get("data") or {}).get("object") or {}
        base = {"id": str(evt.get("id", "")), "provider_type": et, "type": "ignored"}
        meta = obj.get("metadata") or {}
        if et == "checkout.session.completed":
            if meta.get("kind") == "topup" or obj.get("mode") == "payment":
                return {**base, "type": "topup_completed", "tenant_id": meta.get("tenant_id") or obj.get("client_reference_id", ""),
                        "customer_id": obj.get("customer", ""), "session_id": obj.get("id", ""),
                        "amount_cents": int(obj.get("amount_total") or meta.get("amount_cents") or 0)}
            return {**base, "type": "checkout_completed", "tenant_id": meta.get("tenant_id") or obj.get("client_reference_id", ""),
                    "plan_id": meta.get("plan_id", ""), "customer_id": obj.get("customer", ""),
                    "subscription_id": obj.get("subscription", ""), "session_id": obj.get("id", "")}
        if et in ("customer.subscription.updated", "customer.subscription.created", "customer.subscription.deleted"):
            item = ((obj.get("items") or {}).get("data") or [{}])[0]
            price_id = (item.get("price") or {}).get("id", "")
            return {**base, "type": "subscription_cancelled" if et.endswith("deleted") else "subscription_updated",
                    "tenant_id": meta.get("tenant_id", ""), "plan_id": self._plan_by_price.get(price_id, meta.get("plan_id", "")),
                    "customer_id": obj.get("customer", ""), "subscription_id": obj.get("id", ""),
                    "status": obj.get("status", ""), "cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
                    "period_start": obj.get("current_period_start") or item.get("current_period_start"),
                    "period_end": obj.get("current_period_end") or item.get("current_period_end")}
        if et in ("invoice.payment_failed", "invoice.paid"):
            sub = obj.get("subscription") or (((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")) or ""
            return {**base, "type": "payment_failed" if et.endswith("failed") else "payment_succeeded",
                    "customer_id": obj.get("customer", ""), "subscription_id": sub,
                    "tenant_id": (obj.get("subscription_details") or {}).get("metadata", {}).get("tenant_id", "")}
        return base

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": "stripe", "webhook_secret_configured": bool(self._whsec),
                "prices": sorted(k for k, v in self.price_ids.items() if v)}
