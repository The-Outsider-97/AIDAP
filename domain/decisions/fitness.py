"""The Fitness Decision: AIDAP's authoritative output for a run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..utils.domain_helpers import iso, parse_iso
from .models import ArtifactDisposition, Decision, DecisionStatus, Reason
from .rationale import DecisionRationale

__all__ = ["FitnessDecision"]


@dataclass
class FitnessDecision:
    id: str
    tenant_id: str
    project_id: str
    run_id: str
    decision: Decision
    status: DecisionStatus
    disposition: ArtifactDisposition
    reasons: list[Reason]
    rationale: DecisionRationale
    policy_ref: str                 # "<policy_id>@<version>"
    profile_ref: str                # "<profile_id>@<version>"
    input_digest: str               # digest of the exact artifact the decision is about
    released_digest: str            # digest of the artifact that may be released (== input unless redacted)
    coverage: dict[str, Any]
    created_at: datetime
    expires_at: datetime | None
    shadow: bool = False
    exception_ids: list[str] = field(default_factory=list)
    supersedes: str | None = None
    decided_by: str = "system"       # "system" or a user id after review
    score: float | None = None       # ordering aid only; never overrides a rule

    def release_authorized(self, now: datetime, digest: str | None = None) -> bool:
        """The single gate for delivery. Anything unclear is *not* authorised."""
        if self.shadow or self.status != DecisionStatus.ACTIVE:
            return False
        if self.decision != Decision.PASS:
            return False
        if self.disposition in (ArtifactDisposition.QUARANTINED, ArtifactDisposition.DELETED):
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        if digest is not None and digest != self.released_digest:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tenant_id": self.tenant_id, "project_id": self.project_id, "run_id": self.run_id,
            "decision": self.decision.value, "status": self.status.value, "disposition": self.disposition.value,
            "reasons": [r.to_dict() for r in self.reasons], "rationale": self.rationale.to_dict(),
            "policy_ref": self.policy_ref, "profile_ref": self.profile_ref, "input_digest": self.input_digest,
            "released_digest": self.released_digest, "coverage": self.coverage, "created_at": iso(self.created_at),
            "expires_at": iso(self.expires_at), "shadow": self.shadow, "exception_ids": list(self.exception_ids),
            "supersedes": self.supersedes, "decided_by": self.decided_by, "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FitnessDecision":
        return cls(
            id=d["id"], tenant_id=d["tenant_id"], project_id=d.get("project_id", ""), run_id=d["run_id"],
            decision=Decision(d["decision"]), status=DecisionStatus(d["status"]),
            disposition=ArtifactDisposition(d["disposition"]),
            reasons=[Reason.from_dict(r) for r in d.get("reasons", [])],
            rationale=DecisionRationale.from_dict(d.get("rationale")),
            policy_ref=d.get("policy_ref", ""), profile_ref=d.get("profile_ref", ""),
            input_digest=d.get("input_digest", ""), released_digest=d.get("released_digest", ""),
            coverage=dict(d.get("coverage", {})), created_at=parse_iso(d["created_at"]),
            expires_at=parse_iso(d.get("expires_at")), shadow=bool(d.get("shadow", False)),
            exception_ids=list(d.get("exception_ids", [])), supersedes=d.get("supersedes"),
            decided_by=d.get("decided_by", "system"), score=d.get("score"),
        )
