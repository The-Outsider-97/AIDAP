"""Verify AIDAP webhook deliveries (HMAC-SHA256, replay window).

AIDAP signs through SLAI's webhook service, so the headers keep SLAI's names:
``X-SLAI-Webhook-Id``, ``-Timestamp``, ``-Signature`` (``v1=<hex>``) and ``-Event``.
The signed string is ``<timestamp>.<event id>.<raw body>``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Mapping

__all__ = ["verify_signature", "SignatureError"]

_SIG = re.compile(r"^v1=([0-9a-fA-F]{64})$")


class SignatureError(Exception):
    pass


def verify_signature(secret: str, body: bytes, headers: Mapping[str, str], *, tolerance_seconds: int = 300, now: float | None = None) -> None:
    """Raise ``SignatureError`` unless the delivery is authentic and recent. Pass the *raw* request body."""
    h = {k.lower(): v for k, v in headers.items()}
    try:
        ts, event_id, sig = int(h["x-slai-webhook-timestamp"]), h["x-slai-webhook-id"], h["x-slai-webhook-signature"].strip()
    except (KeyError, ValueError) as exc:
        raise SignatureError("missing or malformed webhook headers") from exc
    if not _SIG.fullmatch(sig):
        raise SignatureError("malformed signature")
    if abs((now if now is not None else time.time()) - ts) > tolerance_seconds:
        raise SignatureError("timestamp outside the replay window")
    expected = hmac.new(secret.encode("utf-8"), f"{ts}.{event_id}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"v1={expected}", sig):
        raise SignatureError("signature mismatch")
