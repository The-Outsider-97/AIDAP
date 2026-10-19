"""Operational records produced around a run: review items, quarantine, alerts, audit, deliveries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..utils.records import Record

__all__ = ["ReviewItem", "QuarantineItem", "Alert", "AuditEvent", "DeliveryRecord", "Schedule", "OutboxEvent"]


@dataclass
class ReviewItem(Record):
    id: str
    tenant_id: str
    project_id: str
    run_id: str
    decision_id: str
    state: str
    reason_codes: list[str]
    summary: str
    created_at: datetime
    assignee: str = ""
    due_at: datetime | None = None
    resolved_by: str = ""
    resolved_at: datetime | None = None
    resolution: str = ""
    comment: str = ""
    exception_id: str = ""
    previous_run_id: str = ""        # last approved comparable run, for the "difference" view


@dataclass
class QuarantineItem(Record):
    id: str
    tenant_id: str
    project_id: str
    run_id: str
    version_id: str
    blob_ref: str
    reason_codes: list[str]
    created_at: datetime
    retain_until: datetime
    state: str = "held"              # held | released_for_investigation | deleted
    last_accessed_by: str = ""
    last_accessed_at: datetime | None = None
    disposed_by: str = ""
    disposed_at: datetime | None = None


@dataclass
class Alert(Record):
    id: str
    tenant_id: str
    project_id: str
    kind: str
    dedupe_key: str
    title: str
    detail: str
    severity: str
    created_at: datetime
    count: int = 1
    last_seen_at: datetime | None = None
    run_id: str = ""
    acknowledged_by: str = ""
    acknowledged_at: datetime | None = None


@dataclass
class AuditEvent(Record):
    id: str
    tenant_id: str
    actor: str
    actor_kind: str
    action: str
    target: str
    at: datetime
    correlation_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""


@dataclass
class DeliveryRecord(Record):
    id: str
    tenant_id: str
    project_id: str
    run_id: str
    decision_id: str
    destination_id: str
    kind: str
    digest: str
    state: str                       # pending | sent | failed | blocked | dead
    created_at: datetime
    attempts: int = 0
    last_error: str = ""
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None
    idempotency_key: str = ""
    response_status: int | None = None


@dataclass
class Schedule(Record):
    id: str
    tenant_id: str
    project_id: str
    name: str
    interval_minutes: int
    source_url: str
    profile_id: str
    policy_id: str
    destination_id: str
    created_by: str
    created_at: datetime
    next_run_at: datetime | None = None
    enabled: bool = True
    last_run_at: datetime | None = None
    last_run_id: str = ""
    last_error: str = ""


@dataclass
class OutboxEvent(Record):
    id: str
    tenant_id: str
    kind: str                         # email | webhook
    payload: dict[str, Any]
    created_at: datetime
    state: str = "pending"            # pending | sent | failed | dead
    attempts: int = 0
    next_attempt_at: datetime | None = None
    last_error: str = ""
    dedupe_key: str = ""
