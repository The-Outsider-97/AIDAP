"""AES-256-GCM sealing for stored secrets and artifacts, with key ids so keys can be rotated."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ...domain.utils.domain_errors import IntegrityViolation, Unavailable

__all__ = ["AesGcmSecretBox", "load_keys"]

_MAGIC = b"AID1"


def _kid(key: bytes) -> bytes:
    return hashlib.sha256(b"aidap-kid" + key).digest()[:4]


def load_keys(env_value: str | None, key_file: Path, *, allow_generate: bool) -> list[bytes]:
    """``AIDAP_SECRET_KEYS`` = comma-separated base64 32-byte keys, newest first. In development a key is generated
    once and kept in the data directory with owner-only permissions; production must supply it."""
    keys: list[bytes] = []
    for part in (env_value or "").split(","):
        part = part.strip()
        if not part:
            continue
        raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        if len(raw) != 32:
            raise Unavailable("AIDAP_SECRET_KEYS entries must decode to exactly 32 bytes", code="config_error")
        keys.append(raw)
    if keys:
        return keys
    if key_file.exists():
        return [base64.urlsafe_b64decode(key_file.read_text().strip())]
    if not allow_generate:
        raise Unavailable("AIDAP_SECRET_KEYS is required in production", code="config_error")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(base64.urlsafe_b64encode(raw).decode())
    return [raw]


class AesGcmSecretBox:
    def __init__(self, keys: list[bytes]) -> None:
        if not keys:
            raise ValueError("at least one key is required")
        self._keys = {_kid(k): AESGCM(k) for k in keys}
        self._current = _kid(keys[0])

    def seal_bytes(self, plaintext: bytes, *, aad: bytes = b"") -> bytes:
        nonce = secrets.token_bytes(12)
        ct = self._keys[self._current].encrypt(nonce, plaintext, aad)
        return _MAGIC + self._current + nonce + ct

    def open_bytes(self, sealed: bytes, *, aad: bytes = b"") -> bytes:
        if len(sealed) < 4 + 4 + 12 + 16 or sealed[:4] != _MAGIC:
            raise IntegrityViolation("sealed data is malformed")
        kid, nonce, ct = sealed[4:8], sealed[8:20], sealed[20:]
        box = self._keys.get(kid)
        if box is None:
            raise IntegrityViolation("sealed data was written with an unknown key")
        try:
            return box.decrypt(nonce, ct, aad)
        except InvalidTag as exc:
            raise IntegrityViolation("sealed data failed authentication") from exc

    def seal(self, plaintext: bytes, *, aad: bytes = b"") -> str:
        return base64.urlsafe_b64encode(self.seal_bytes(plaintext, aad=aad)).decode("ascii")

    def open(self, sealed: str, *, aad: bytes = b"") -> bytes:
        try:
            raw = base64.urlsafe_b64decode(sealed + "=" * (-len(sealed) % 4))
        except Exception as exc:                                    # noqa: BLE001
            raise IntegrityViolation("sealed secret is malformed") from exc
        return self.open_bytes(raw, aad=aad)
