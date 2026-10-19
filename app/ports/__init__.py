"""Ports: everything the application layer needs from the outside world, as Protocols.

Adapters live in ``infra/`` (persistence, queue, crypto, billing, ...) and ``slai/`` (the SLAI runtime). The domain,
the assurance engine and the app layer import nothing from either.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = ["DocStore", "BlobStore", "Job", "JobQueue", "PasswordService", "SecretBox", "TokenService", "TotpService",
           "MalwareScanner", "Mailer", "WebhookSender", "WebhookResult", "BillingGateway", "RateLimiterPort",
           "Clock", "StageCheckpoints", "SafeFetcher", "FetchResult", "ObjectDelivery", "ReasoningGateway"]

Where = dict[str, Any]


class DocStore(Protocol):
    """Tenant-scoped JSON document persistence with transactions and a hash-chained audit log."""

    def transaction(self) -> AbstractContextManager[Any]: ...

    def insert(self, coll: str, doc: dict[str, Any], *, tenant_id: str = "", ukey: str | None = None) -> bool:
        """Insert; ``False`` (and no change) if the id or ``ukey`` already exists in the collection."""

    def put(self, coll: str, doc: dict[str, Any], *, tenant_id: str = "", ukey: str | None = None) -> None: ...

    def get(self, coll: str, doc_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None: ...

    def get_by_ukey(self, coll: str, ukey: str) -> dict[str, Any] | None: ...

    def find(self, coll: str, *, tenant_id: str | None = None, where: Where | None = None,
             order_by: str = "created_at", desc: bool = True, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]: ...

    def count(self, coll: str, *, tenant_id: str | None = None, where: Where | None = None) -> int: ...

    def delete(self, coll: str, doc_id: str, *, tenant_id: str | None = None) -> bool: ...

    def append_audit(self, tenant_id: str, event: dict[str, Any]) -> dict[str, Any]: ...

    def verify_audit(self, tenant_id: str) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str: ...

    def get(self, ref: str) -> bytes: ...

    def delete(self, ref: str) -> None: ...

    def exists(self, ref: str) -> bool: ...


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    dedupe_key: str = ""
    max_attempts: int = 3


class JobQueue(Protocol):
    def enqueue(self, kind: str, payload: dict[str, Any], *, dedupe_key: str = "", run_after: datetime | None = None,
                max_attempts: int = 3) -> str: ...

    def lease(self, kinds: list[str], worker: str, lease_seconds: int = 300) -> Job | None: ...

    def complete(self, job_id: str) -> None: ...

    def fail(self, job_id: str, error: str, *, retry_in_seconds: float | None = None) -> str:
        """Returns the new state: ``queued`` for a retry, ``dead`` when attempts are exhausted."""

    def cancel(self, dedupe_key: str) -> int: ...

    def stats(self) -> dict[str, int]: ...


class PasswordService(Protocol):
    def validate(self, password: str) -> None: ...

    def hash(self, password: str) -> tuple[str, str]: ...

    def verify(self, password: str, salt: str, digest: str) -> bool: ...


class SecretBox(Protocol):
    """Authenticated encryption for secrets and stored artifacts (AES-256-GCM)."""

    def seal(self, plaintext: bytes, *, aad: bytes = b"") -> str: ...

    def open(self, sealed: str, *, aad: bytes = b"") -> bytes: ...

    def seal_bytes(self, plaintext: bytes, *, aad: bytes = b"") -> bytes: ...

    def open_bytes(self, sealed: bytes, *, aad: bytes = b"") -> bytes: ...


class TokenService(Protocol):
    def new(self, prefix: str, nbytes: int = 32) -> tuple[str, str]:
        """``(token, digest)``; only the digest is persisted."""

    def digest(self, token: str) -> str: ...

    def equal(self, a: str, b: str) -> bool: ...


class TotpService(Protocol):
    def new_secret(self) -> str: ...

    def uri(self, secret: str, account: str, issuer: str) -> str: ...

    def verify(self, secret: str, code: str, *, last_counter: int = 0, now: datetime | None = None) -> int | None:
        """Matching time-step counter, or ``None``. A counter <= ``last_counter`` is a replay and fails."""


class MalwareScanner(Protocol):
    def scan(self, data: bytes) -> dict[str, Any]:
        """``{"engine", "status": clean|infected|unavailable|error, "signature"}``. Never "clean" when unsure."""

    def health(self) -> dict[str, Any]: ...


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, *, html: str = "", reply_to: str = "") -> None: ...

    def health(self) -> dict[str, Any]: ...


@dataclass
class WebhookResult:
    ok: bool
    status: int | None = None
    retryable: bool = False
    error: str = ""
    attempts: int = 1


class WebhookSender(Protocol):
    def validate_target(self, url: str) -> None:
        """Raise if ``url`` is not an acceptable (HTTPS, public) webhook target. Sends nothing."""

    def send(self, url: str, secret: str, event_id: str, payload: dict[str, Any]) -> WebhookResult: ...


class BillingGateway(Protocol):
    provider: str

    def create_customer(self, tenant_id: str, email: str, name: str) -> str: ...

    def create_checkout(self, *, tenant_id: str, customer_id: str, plan_id: str, success_url: str,
                        cancel_url: str, idempotency_key: str) -> dict[str, Any]: ...

    def create_portal(self, customer_id: str, return_url: str) -> str: ...

    def cancel_subscription(self, provider_subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]: ...

    def create_topup(self, *, tenant_id: str, customer_id: str, amount_cents: int, success_url: str,
                     cancel_url: str, idempotency_key: str) -> dict[str, Any]: ...

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Verify the provider signature and return a normalised event; raise on any failure."""

    def health(self) -> dict[str, Any]: ...


class RateLimiterPort(Protocol):
    def check(self, key: str, tokens: int = 1) -> tuple[bool, float]:
        """``(allowed, retry_after_seconds)``; consumes ``tokens`` only when allowed."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class StageCheckpoints(Protocol):
    """Per-run durable stage outputs (backed by SLAI's CheckpointManager when available)."""

    def store_for(self, run_id: str) -> Any: ...

    def drop(self, run_id: str) -> None: ...

    def health(self) -> dict[str, Any]: ...


@dataclass
class FetchResult:
    data: bytes
    media_type: str = ""
    filename: str = ""
    final_url: str = ""
    etag: str = ""


class SafeFetcher(Protocol):
    def fetch(self, url: str, *, max_bytes: int) -> FetchResult: ...


class ObjectDelivery(Protocol):
    def deliver(self, key: str, data: bytes, *, content_type: str = "") -> str: ...


class ReasoningGateway(Protocol):
    """The only door through which a model is consulted. Returns a payload that the app validates."""

    def available(self) -> tuple[bool, str]: ...

    def reason(self, request: dict[str, Any]) -> dict[str, Any]: ...
