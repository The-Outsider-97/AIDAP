"""Opaque token generation with HMAC-peppered digests: a database leak does not yield usable tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets

__all__ = ["HmacTokenService"]


class HmacTokenService:
    def __init__(self, pepper: str) -> None:
        if len(pepper) < 16:
            raise ValueError("token pepper must be at least 16 characters")
        self._key = pepper.encode("utf-8")

    def new(self, prefix: str, nbytes: int = 32) -> tuple[str, str]:
        token = f"{prefix}_{secrets.token_urlsafe(nbytes)}"
        return token, self.digest(token)

    def digest(self, token: str) -> str:
        return hmac.new(self._key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def equal(self, a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
