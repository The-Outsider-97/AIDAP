"""Settings and the dependency bundle injected into every service (built once, in ``bootstrap``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.accounts.plans import Plan
from .ports import (BillingGateway, BlobStore, Clock, DocStore, JobQueue, Mailer, MalwareScanner, ObjectDelivery,
                    PasswordService, RateLimiterPort, SafeFetcher, SecretBox, StageCheckpoints, TokenService,
                    TotpService, WebhookSender)

__all__ = ["Settings", "Deps"]


@dataclass
class Settings:
    environment: str = "development"
    base_url: str = "http://127.0.0.1:8780"
    business_email: str = "info.remy3design@gmail.com"
    data_dir: str = "./var"
    inline_workers: bool = True
    poll_seconds: float = 1.0
    lease_seconds: int = 300
    max_attempts: int = 3
    max_upload_bytes: int = 100 * 1024 * 1024
    max_text_chars: int = 5_000_000
    parse_timeout: int = 20
    request_rate_per_minute: int = 240
    login_rate_per_minute: int = 10
    session_hours: int = 12
    csrf: bool = True
    password_min_length: int = 12
    mfa_issuer: str = "AIDAP"
    billing_provider: str = "sandbox"
    auto_overage: bool = False
    past_due_grace_days: int = 7
    allow_http_targets: bool = False          # development only: permit http:// webhook/fetch targets
    allow_private_targets: bool = False       # development/tests only: permit loopback/private targets
    cookie_secure: bool = False
    lockout_attempts: int = 5
    lockout_minutes: int = 15
    invitation_days: int = 7
    quarantine_retention_days: int = 30
    slai_enabled: bool = True
    brand: str = "AIDAP"

    @property
    def production(self) -> bool:
        return self.environment == "production"


class _SystemClock:
    def now(self):                                        # noqa: ANN201
        from ..domain.utils.domain_helpers import utcnow
        return utcnow()


@dataclass
class Deps:
    settings: Settings
    db: DocStore
    blobs: BlobStore
    queue: JobQueue
    passwords: PasswordService
    box: SecretBox
    tokens: TokenService
    totp: TotpService
    scanner: MalwareScanner
    mailer: Mailer
    webhooks: WebhookSender
    billing: BillingGateway
    limiter: RateLimiterPort
    login_limiter: RateLimiterPort
    checkpoints: StageCheckpoints
    fetcher: SafeFetcher
    objects: ObjectDelivery
    plans: dict[str, Plan]
    catalog: Any                                          # TemplateCatalog (app/services/catalog.py)
    slai: Any = None                                      # SlaiRuntime or None
    configs: Any = None                                   # ConfigService (set by build_services)
    clock: Clock = field(default_factory=_SystemClock)

    def now(self):                                        # noqa: ANN201
        return self.clock.now()
