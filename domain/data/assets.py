"""Projects, assets, immutable input versions, destinations and baselines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..utils.records import Record

__all__ = ["Project", "DataAsset", "InputVersion", "Destination", "Baseline", "BaselineStatus"]


@dataclass
class Project(Record):
    id: str
    tenant_id: str
    name: str
    slug: str
    created_at: datetime
    description: str = ""
    default_profile_id: str = ""
    default_policy_id: str = "standard"
    default_destination_id: str = ""
    archived: bool = False


@dataclass
class DataAsset(Record):
    id: str
    tenant_id: str
    project_id: str
    name: str
    created_at: datetime
    source_class: str = "unknown"
    classification: str = "internal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InputVersion(Record):
    """An immutable input. Its identity is the digest of the original bytes."""

    id: str
    tenant_id: str
    project_id: str
    asset_id: str
    version_no: int
    content_digest: str
    size: int
    blob_ref: str
    created_at: datetime
    created_by: str
    filename: str = ""
    media_type: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)   # owner, source_revision, effective_date...
    derived_from: str | None = None       # parent InputVersion id
    derivation: str = ""                  # e.g. "redaction"
    purged: bool = False                  # blob deleted per retention; digest and evidence remain


@dataclass
class Destination(Record):
    id: str
    tenant_id: str
    project_id: str
    name: str
    klass: str                         # DestinationClass value
    created_at: datetime
    delivery: str = "pull"             # DeliveryKind value
    target_url: str = ""               # webhook / object-store URL (validated at use; SSRF-safe)
    secret_ref: str = ""               # sealed secret holder id (never the secret itself)
    enabled: bool = True
    description: str = ""


class BaselineStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RETIRED = "retired"


@dataclass
class Baseline(Record):
    """A reference population. Proposed is *not* approved: the first batch is never implicitly trusted."""

    id: str
    tenant_id: str
    project_id: str
    profile_id: str
    name: str
    version: int
    status: BaselineStatus
    stats: dict[str, Any]
    sample_size: int
    proposed_by: str
    created_at: datetime
    source_run_id: str = ""
    schema_signature: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    retired_at: datetime | None = None
