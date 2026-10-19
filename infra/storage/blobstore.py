"""Encrypted blob storage on SLAI's ``Storage`` + ``FileTransferService`` (local disk, or S3 via SLAI's S3 backend).

Artifacts are sealed with AES-256-GCM before they reach the backend, with the object key as associated data, so a
swapped or tampered object fails authentication instead of being served.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

from ...domain.utils.domain_errors import IntegrityViolation, NotFound
from ...slai.runtime import functions
from ..crypto.secretbox import AesGcmSecretBox

__all__ = ["SlaiBlobStore", "SlaiObjectDelivery"]


class SlaiBlobStore:
    def __init__(self, base_dir: str, box: AesGcmSecretBox, *, max_bytes: int = 512 * 1024 * 1024,
                 backend: object | None = None) -> None:
        st = functions("storage")
        ft = functions("file_transfer")
        self._err = st.StorageError
        self._missing = st.StorageNotFoundError
        backend = backend or st.LocalStorage(base_path=base_dir)
        self.storage = st.Storage(backend, generate_unique_filename=False)     # deterministic keys
        policy = ft.TransferPolicy(max_bytes=max_bytes, chunk_size=min(1024 * 1024, max_bytes))
        self.transfer = ft.FileTransferService(self.storage, policy=policy)
        self.box = box

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        p = PurePosixPath(key)
        sealed = self.box.seal_bytes(data, aad=key.encode())
        receipt = self.transfer.upload_bytes(sealed, filename=p.name, subpath=str(p.parent) if str(p.parent) != "." else "",
                                             content_type="application/octet-stream",
                                             expected_sha256=hashlib.sha256(sealed).hexdigest())
        return receipt.object_key or key

    def get(self, ref: str) -> bytes:
        try:
            sealed = self.storage.download(ref)
        except self._missing as exc:
            raise NotFound("stored object is missing", code="blob_missing") from exc
        except self._err as exc:
            raise IntegrityViolation(f"stored object could not be read: {exc}") from exc
        return self.box.open_bytes(sealed, aad=ref.encode())

    def delete(self, ref: str) -> None:
        try:
            self.storage.delete(ref)
        except self._missing:
            return

    def exists(self, ref: str) -> bool:
        try:
            self.storage.download(ref)
            return True
        except self._err:
            return False


class SlaiObjectDelivery:
    """Delivery of approved artifacts to an operator-configured object store (plain bytes, by design)."""

    def __init__(self, base_dir: str, backend: object | None = None) -> None:
        st = functions("storage")
        self.storage = st.Storage(backend or st.LocalStorage(base_path=base_dir), generate_unique_filename=False)

    def deliver(self, key: str, data: bytes, *, content_type: str = "") -> str:
        import io
        p = PurePosixPath(key)
        return self.storage.upload(io.BytesIO(data), p.name, subpath=str(p.parent) if str(p.parent) != "." else "",
                                   metadata={"content_type": content_type} if content_type else None)
