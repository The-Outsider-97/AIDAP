"""Tenants, users, memberships and subscriptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..utils.records import Record

__all__ = ["SubscriptionStatus", "Tenant", "User", "Membership", "Subscription", "ApiKeyRecord",
           "SessionRecord", "Invitation", "CheckoutRecord"]


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"       # grace period applies; entitlements fall back after it
    CANCELLED = "cancelled"     # access continues to period end
    EXPIRED = "expired"


@dataclass
class Tenant(Record):
    id: str
    name: str
    slug: str
    created_at: datetime
    owner_user_id: str = ""
    billing_email: str = ""
    retention_days: int | None = None        # configurable (Business+), otherwise plan default
    settings: dict[str, Any] = field(default_factory=dict)
    suspended: bool = False
    deleted_at: datetime | None = None


@dataclass
class User(Record):
    id: str
    email: str
    name: str
    password_salt: str
    password_hash: str
    created_at: datetime
    email_verified: bool = False
    failed_attempts: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    mfa_enabled: bool = False
    mfa_secret_sealed: str = ""            # AES-GCM sealed TOTP secret
    mfa_last_counter: int = 0              # TOTP replay guard
    recovery_hashes: list[str] = field(default_factory=list)
    disabled: bool = False


@dataclass
class Membership(Record):
    id: str
    tenant_id: str
    user_id: str
    role: str
    created_at: datetime
    project_ids: list[str] = field(default_factory=list)   # empty = all projects


@dataclass
class Subscription(Record):
    id: str
    tenant_id: str
    plan_id: str
    status: SubscriptionStatus
    provider: str                           # "sandbox" | "stripe" | "none"
    created_at: datetime
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    provider_customer_id: str = ""
    provider_subscription_id: str = ""
    past_due_since: datetime | None = None
    pending_plan_id: str = ""               # downgrade scheduled for period end
    topup_inference_cents: int = 0          # prepaid managed-inference balance
    auto_overage: bool = False              # off by default (whitepaper)
    hold_on_exhaustion: bool = True


@dataclass
class ApiKeyRecord(Record):
    id: str
    tenant_id: str
    name: str
    prefix: str
    digest: str
    scopes: list[str]
    created_by: str
    created_at: datetime
    project_ids: list[str] = field(default_factory=list)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


@dataclass
class SessionRecord(Record):
    id: str
    user_id: str
    digest: str
    csrf_digest: str
    created_at: datetime
    expires_at: datetime
    tenant_id: str = ""
    ip: str = ""
    user_agent: str = ""
    mfa_passed: bool = True
    revoked_at: datetime | None = None


@dataclass
class Invitation(Record):
    id: str
    tenant_id: str
    email: str
    role: str
    digest: str
    invited_by: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    project_ids: list[str] = field(default_factory=list)


@dataclass
class CheckoutRecord(Record):
    id: str
    tenant_id: str
    plan_id: str
    provider: str
    status: str
    created_at: datetime
    url: str = ""
    provider_session_id: str = ""
    completed_at: datetime | None = None
