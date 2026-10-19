"""Decision vocabulary. Decision status, artifact disposition and job state are
three separate state machines (whitepaper 7.1) and must never be conflated."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..evaluations.severity import Severity
from ..utils.domain_errors import InvalidTransition
from ..utils.domain_helpers import iso, parse_iso

__all__ = ["Decision", "Effect", "DecisionStatus", "ArtifactDisposition", "Reason", "ExceptionGrant",
           "assert_status_transition", "combine", "NON_WAIVABLE_PREFIXES", "exception_allowed_for"]


class Decision(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    BLOCK = "block"

    @property
    def rank(self) -> int:
        return ("pass", "review", "quarantine", "block").index(self.value)

    @classmethod
    def parse(cls, value: "str | Decision | None", default: "Decision | None" = None) -> "Decision":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            if default is not None:
                return default
            raise


# A policy "effect" is the decision a single rule contributes; same vocabulary.
Effect = Decision


def combine(effects: list[Decision]) -> Decision:
    """Worst-of. Averaging can never erase a prohibition."""
    if not effects:
        return Decision.PASS
    return max(effects, key=lambda e: e.rank)


class DecisionStatus(str, Enum):
    ACTIVE = "active"            # the current decision for the run
    SUPERSEDED = "superseded"    # replaced by a newer decision (history is never rewritten)
    EXPIRED = "expired"          # validity window elapsed; release no longer authorised
    SHADOW = "shadow"            # computed under a shadow-mode policy; never authorises release


class ArtifactDisposition(str, Enum):
    RETAINED = "retained"        # stored, not released
    RELEASED = "released"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


_ALLOWED = {
    DecisionStatus.ACTIVE: {DecisionStatus.SUPERSEDED, DecisionStatus.EXPIRED},
    DecisionStatus.SHADOW: {DecisionStatus.SUPERSEDED},
    DecisionStatus.EXPIRED: {DecisionStatus.SUPERSEDED},
    DecisionStatus.SUPERSEDED: set(),
}


def assert_status_transition(old: DecisionStatus, new: DecisionStatus) -> None:
    if new == old:
        return
    if new not in _ALLOWED.get(old, set()):
        raise InvalidTransition(f"decision status cannot change from {old.value} to {new.value}")


# Reason codes under these prefixes can never be waived by an exception grant.
NON_WAIVABLE_PREFIXES = ("safety.malicious", "safety.file.malware", "safety.injection.tool", "privacy.secret",
                         "incomplete.safety", "policy.prohibited_destination")


def exception_allowed_for(code: str) -> bool:
    return not any(code == p or code.startswith(p + ".") or code.startswith(p) for p in NON_WAIVABLE_PREFIXES)


@dataclass
class Reason:
    code: str
    message: str
    effect: Decision
    severity: Severity = Severity.MEDIUM
    check_id: str = ""
    finding_ids: list[str] = field(default_factory=list)
    rule_id: str | None = None
    waivable: bool = True
    guidance: str = ""
    waived_by: str | None = None          # exception grant id when an authorised exception covers this reason

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "effect": self.effect.value,
                "severity": self.severity.value, "check_id": self.check_id,
                "finding_ids": list(self.finding_ids), "rule_id": self.rule_id,
                "waivable": self.waivable, "guidance": self.guidance, "waived_by": self.waived_by}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Reason":
        return cls(d["code"], d.get("message", ""), Decision(d["effect"]), Severity.parse(d.get("severity")),
                   d.get("check_id", ""), list(d.get("finding_ids", [])), d.get("rule_id"),
                   bool(d.get("waivable", True)), d.get("guidance", ""), d.get("waived_by"))


@dataclass
class ExceptionGrant:
    """An attributable, scoped, expiring human exception."""

    id: str
    tenant_id: str
    run_id: str
    review_id: str
    reason_codes: list[str]
    granted_by: str
    granted_role: str
    justification: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False

    def active(self, now: datetime) -> bool:
        return not self.revoked and now < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "tenant_id": self.tenant_id, "run_id": self.run_id,
                "review_id": self.review_id, "reason_codes": list(self.reason_codes),
                "granted_by": self.granted_by, "granted_role": self.granted_role,
                "justification": self.justification, "created_at": iso(self.created_at),
                "expires_at": iso(self.expires_at), "revoked": self.revoked}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExceptionGrant":
        return cls(d["id"], d["tenant_id"], d["run_id"], d.get("review_id", ""), list(d.get("reason_codes", [])),
                   d["granted_by"], d.get("granted_role", ""), d.get("justification", ""),
                   parse_iso(d["created_at"]), parse_iso(d["expires_at"]), bool(d.get("revoked", False)))
