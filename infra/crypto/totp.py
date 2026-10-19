"""RFC 6238 TOTP (SHA-1, 30 s, 6 digits, +/-1 step) with a replay guard on the matched time-step counter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime
from urllib.parse import quote

__all__ = ["Rfc6238Totp"]


class Rfc6238Totp:
    def __init__(self, step: int = 30, digits: int = 6, window: int = 1) -> None:
        self.step, self.digits, self.window = step, digits, window

    def new_secret(self) -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    def uri(self, secret: str, account: str, issuer: str) -> str:
        return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
                f"&algorithm=SHA1&digits={self.digits}&period={self.step}")

    def _code(self, secret: str, counter: int) -> str:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
        mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        off = mac[-1] & 0x0F
        num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** self.digits)
        return str(num).zfill(self.digits)

    def at(self, secret: str, when: float) -> str:
        return self._code(secret, int(when // self.step))

    def verify(self, secret: str, code: str, *, last_counter: int = 0, now: datetime | None = None) -> int | None:
        code = (code or "").strip().replace(" ", "")
        if len(code) != self.digits or not code.isdigit():
            return None
        t = now.timestamp() if now else time.time()
        base = int(t // self.step)
        matched: int | None = None
        for delta in range(-self.window, self.window + 1):          # constant work for every candidate
            counter = base + delta
            if hmac.compare_digest(self._code(secret, counter), code) and matched is None:
                matched = counter
        if matched is None or matched <= last_counter:
            return None
        return matched
