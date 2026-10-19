"""Decision rationale and reason guidance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Decision

__all__ = ["RationaleStep", "DecisionRationale", "REASON_GUIDANCE", "guidance"]


@dataclass
class RationaleStep:
    rule_id: str
    description: str
    outcome: Decision
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "description": self.description,
                "outcome": self.outcome.value, "reason_codes": list(self.reason_codes)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RationaleStep":
        return cls(d["rule_id"], d.get("description", ""), Decision(d["outcome"]), list(d.get("reason_codes", [])))


@dataclass
class DecisionRationale:
    summary: str
    steps: list[RationaleStep] = field(default_factory=list)
    next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "steps": [s.to_dict() for s in self.steps],
                "next_action": self.next_action}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "DecisionRationale":
        d = d or {}
        return cls(d.get("summary", ""), [RationaleStep.from_dict(s) for s in d.get("steps", [])],
                   d.get("next_action", ""))


# Ordered: longest/most specific prefixes first.
REASON_GUIDANCE: list[tuple[str, str]] = [
    ("privacy.secret", "Remove the credential, rotate it, and resubmit. Credentials are never released."),
    ("privacy.destination", "Redact the listed values or choose a destination whose profile permits them, then resubmit."),
    ("privacy.pii", "Create a redacted version from the findings page; it is re-validated as a new input."),
    ("safety.malicious", "Keep the artifact quarantined and investigate the source. This cannot be waived."),
    ("safety.file", "Do not open or index this file. Obtain a clean copy from the original owner."),
    ("safety.injection", "Remove the embedded instructions and resubmit, or have a security reviewer assess them."),
    ("temporal.expired", "Provide the current version or an approved extension of the validity period."),
    ("temporal.superseded", "Submit the replacing revision instead of this one."),
    ("quality.structural", "Fix the listed fields and resubmit; the findings cite exact locations."),
    ("quality.metadata", "Add the required metadata (owner, revision, effective date) and resubmit."),
    ("quality.duplicates", "Remove duplicate records or confirm they are intended."),
    ("quality.statistical", "Review missingness and sample size against the profile thresholds."),
    ("quality.anomaly", "Confirm the change is intended and, if so, propose and approve a new baseline."),
    ("semantic.conflicts", "Resolve the conflicting statements; both cited spans must agree."),
    ("semantic.rules", "Adjust the content or the profile rule that fired."),
    ("fitness.", "Choose a profile that matches this source, audience and destination."),
    ("incomplete.", "A mandatory check could not complete. Retry, or have a reviewer decide with the coverage shown."),
    ("policy.", "The policy prohibits this use; change the destination or the policy through its approval workflow."),
    ("intake.", "The file could not be read as a supported format. Convert it and resubmit."),
    ("slai.", "Model-assisted finding: a reviewer must confirm it. It cannot block on its own."),
]


def guidance(code: str) -> str:
    for prefix, text in REASON_GUIDANCE:
        if code.startswith(prefix):
            return text
    return "Review the finding details and decide whether to repair the input or grant a scoped exception."
