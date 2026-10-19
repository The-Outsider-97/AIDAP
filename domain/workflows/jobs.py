"""Job state (separate from decision status and artifact disposition)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..utils.domain_helpers import iso, parse_iso

__all__ = ["JobState", "StageState", "StageRecord", "AssuranceRun", "TERMINAL_JOB_STATES"]


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"       # decision committed
    FAILED = "failed"             # unrecoverable; the decision is never PASS
    CANCELLED = "cancelled"
    HELD = "held"                 # plan exhausted / budget: new optional work paused


TERMINAL_JOB_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


class StageState(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageRecord:
    run_id: str
    stage: int
    state: StageState
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    checkpoint: str | None = None      # SLAI CheckpointManager version holding the stage output
    output_digest: str = ""
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "stage": self.stage, "state": self.state.value, "attempt": self.attempt,
                "started_at": iso(self.started_at), "finished_at": iso(self.finished_at),
                "checkpoint": self.checkpoint, "output_digest": self.output_digest, "message": self.message,
                "metrics": self.metrics}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StageRecord":
        return cls(d["run_id"], int(d["stage"]), StageState(d["state"]), int(d.get("attempt", 1)),
                   parse_iso(d.get("started_at")), parse_iso(d.get("finished_at")), d.get("checkpoint"),
                   d.get("output_digest", ""), d.get("message", ""), dict(d.get("metrics", {})))


@dataclass
class AssuranceRun:
    id: str
    tenant_id: str
    project_id: str
    asset_id: str
    version_id: str
    profile_id: str
    profile_version: int
    policy_id: str
    policy_version: int
    destination_id: str | None
    state: JobState
    created_by: str
    created_at: datetime
    idempotency_key: str = ""
    input_digest: str = ""
    baseline_id: str | None = None
    decision_id: str | None = None
    decision: str | None = None           # denormalised for listing; the decision record is authoritative
    attempts: int = 0
    error: str = ""
    finished_at: datetime | None = None
    parent_run_id: str | None = None       # set for redacted/re-run derivatives
    source: str = "api"                    # api | ui | schedule | sdk
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tenant_id": self.tenant_id, "project_id": self.project_id, "asset_id": self.asset_id,
            "version_id": self.version_id, "profile_id": self.profile_id, "profile_version": self.profile_version,
            "policy_id": self.policy_id, "policy_version": self.policy_version, "destination_id": self.destination_id,
            "state": self.state.value, "created_by": self.created_by, "created_at": iso(self.created_at),
            "idempotency_key": self.idempotency_key, "input_digest": self.input_digest,
            "baseline_id": self.baseline_id, "decision_id": self.decision_id, "decision": self.decision,
            "attempts": self.attempts, "error": self.error, "finished_at": iso(self.finished_at),
            "parent_run_id": self.parent_run_id, "source": self.source, "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AssuranceRun":
        return cls(
            d["id"], d["tenant_id"], d["project_id"], d.get("asset_id", ""), d.get("version_id", ""),
            d["profile_id"], int(d["profile_version"]), d["policy_id"], int(d["policy_version"]),
            d.get("destination_id"), JobState(d["state"]), d.get("created_by", ""), parse_iso(d["created_at"]),
            d.get("idempotency_key", ""), d.get("input_digest", ""), d.get("baseline_id"), d.get("decision_id"),
            d.get("decision"), int(d.get("attempts", 0)), d.get("error", ""), parse_iso(d.get("finished_at")),
            d.get("parent_run_id"), d.get("source", "api"), d.get("label", ""))
