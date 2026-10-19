"""Intended-use profiles and assurance policies.

Both are customer-editable *data*, versioned and published through an approval
workflow. Nothing in the engine reads a threshold from code that a policy can
express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..data.classification import DataClassification, DestinationClass, SourceClass
from ..decisions.models import Decision
from ..evaluations.severity import Severity
from ..utils.domain_errors import ValidationFailed

__all__ = ["PrivacyRestrictions", "IntendedUseProfile", "PolicyRule", "ExceptionRule", "AssurancePolicy",
           "DEFAULT_SEVERITY_EFFECTS"]

DEFAULT_SEVERITY_EFFECTS: dict[str, str] = {
    "critical": "quarantine", "high": "review", "medium": "review", "low": "pass", "info": "pass",
}


def _list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


@dataclass
class PrivacyRestrictions:
    purpose: str = ""
    allowed_types: list[str] = field(default_factory=list)       # sensitive types acceptable at the destination
    external_forbidden_types: list[str] = field(default_factory=lambda: [
        "api_secret", "private_key", "password_assignment", "access_token", "national_id", "iban",
        "credit_card"])
    redact_instead_of_block: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"purpose": self.purpose, "allowed_types": list(self.allowed_types),
                "external_forbidden_types": list(self.external_forbidden_types),
                "redact_instead_of_block": self.redact_instead_of_block}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "PrivacyRestrictions":
        d = d or {}
        base = cls()
        return cls(str(d.get("purpose", "")), [str(x) for x in _list(d.get("allowed_types"))],
                   [str(x) for x in _list(d.get("external_forbidden_types", base.external_forbidden_types))],
                   bool(d.get("redact_instead_of_block", True)))


@dataclass
class IntendedUseProfile:
    id: str
    name: str
    task: str = ""
    description: str = ""
    audience: list[str] = field(default_factory=list)
    source_classes: list[str] = field(default_factory=list)
    max_classification: str = "internal"
    destinations: list[str] = field(default_factory=lambda: ["local_index"])
    freshness_days: int | None = None
    required_metadata: list[str] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    text_fields: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    semantic_rules: list[dict[str, Any]] = field(default_factory=list)
    privacy: PrivacyRestrictions = field(default_factory=PrivacyRestrictions)
    required_checks: list[str] = field(default_factory=list)
    optional_checks: list[str] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)
    uncertainty: str = "strict"        # "strict": unknown mandatory -> review; "limited": still review, noted
    tags: list[str] = field(default_factory=list)

    # ---- convenience accessors -----------------------------------------------------------
    def threshold(self, name: str, default: Any) -> Any:
        value = self.thresholds.get(name, default)
        return default if value is None else value

    def allows_destination(self, dest: DestinationClass) -> bool:
        return dest.value in self.destinations

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "task": self.task, "description": self.description,
            "audience": list(self.audience), "source_classes": list(self.source_classes),
            "max_classification": self.max_classification, "destinations": list(self.destinations),
            "freshness_days": self.freshness_days, "required_metadata": list(self.required_metadata),
            "fields": [dict(f) for f in self.fields], "text_fields": list(self.text_fields),
            "relationships": [dict(r) for r in self.relationships],
            "semantic_rules": [dict(r) for r in self.semantic_rules], "privacy": self.privacy.to_dict(),
            "required_checks": list(self.required_checks), "optional_checks": list(self.optional_checks),
            "thresholds": dict(self.thresholds), "uncertainty": self.uncertainty, "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IntendedUseProfile":
        if not isinstance(d, dict):
            raise ValidationFailed("profile must be an object")
        pid = str(d.get("id", "")).strip()
        if not pid:
            raise ValidationFailed("profile.id is required")
        fd = d.get("freshness_days")
        return cls(
            id=pid, name=str(d.get("name") or pid), task=str(d.get("task", "")),
            description=str(d.get("description", "")), audience=[str(x) for x in _list(d.get("audience"))],
            source_classes=[str(x) for x in _list(d.get("source_classes"))],
            max_classification=str(d.get("max_classification", "internal")),
            destinations=[str(x) for x in _list(d.get("destinations") or ["local_index"])],
            freshness_days=int(fd) if fd not in (None, "") else None,
            required_metadata=[str(x) for x in _list(d.get("required_metadata"))],
            fields=[dict(x) for x in _list(d.get("fields"))], text_fields=[str(x) for x in _list(d.get("text_fields"))],
            relationships=[dict(x) for x in _list(d.get("relationships"))],
            semantic_rules=[dict(x) for x in _list(d.get("semantic_rules"))],
            privacy=PrivacyRestrictions.from_dict(d.get("privacy")),
            required_checks=[str(x) for x in _list(d.get("required_checks"))],
            optional_checks=[str(x) for x in _list(d.get("optional_checks"))],
            thresholds=dict(d.get("thresholds") or {}), uncertainty=str(d.get("uncertainty", "strict")),
            tags=[str(x) for x in _list(d.get("tags"))],
        )


@dataclass
class PolicyRule:
    id: str
    effect: Decision
    when: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "effect": self.effect.value, "when": dict(self.when),
                "reason": self.reason, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PolicyRule":
        if not isinstance(d, dict) or not d.get("id"):
            raise ValidationFailed("policy rule needs an id")
        try:
            effect = Decision(str(d.get("effect", "")).lower())
        except ValueError:
            raise ValidationFailed(f"policy rule {d.get('id')}: effect must be pass|review|quarantine|block")
        return cls(str(d["id"]), effect, dict(d.get("when") or {}), str(d.get("reason", "")),
                   str(d.get("description", "")))


@dataclass
class ExceptionRule:
    """Which reason codes a reviewer may waive, for how long, and by whom."""

    id: str
    codes: list[str]                      # exact codes or "prefix*"
    max_days: int = 30
    role: str = "reviewer"                # minimum role: reviewer | admin | owner | security
    requires_justification: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "codes": list(self.codes), "max_days": self.max_days, "role": self.role,
                "requires_justification": self.requires_justification}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExceptionRule":
        return cls(str(d.get("id") or "exc"), [str(x) for x in _list(d.get("codes"))],
                   int(d.get("max_days", 30)), str(d.get("role", "reviewer")),
                   bool(d.get("requires_justification", True)))

    def covers(self, code: str) -> bool:
        for pattern in self.codes:
            if pattern.endswith("*"):
                if code.startswith(pattern[:-1]):
                    return True
            elif pattern == code:
                return True
        return False


@dataclass
class AssurancePolicy:
    id: str
    name: str
    description: str = ""
    mode: str = "enforce"                         # "enforce" | "shadow"
    severity_effects: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SEVERITY_EFFECTS))
    rules: list[PolicyRule] = field(default_factory=list)
    exceptions: list[ExceptionRule] = field(default_factory=list)
    unknown_mandatory_effect: str = "review"      # never "pass"
    min_coverage: float = 0.95                    # share of input a mandatory check must examine
    decision_valid_hours: int = 24 * 30
    model_assist: bool = False                    # permit model-assisted (SLAI semantic) checks
    external_inference: bool = False              # permit sending content to a non-local endpoint
    mandatory_overrides: dict[str, bool] = field(default_factory=dict)
    require_baseline: bool = False                # absent approved baseline => review for drift checks
    require_av_scan: bool = False                 # AV engine must have scanned; unavailable => unresolved

    def effect_for_severity(self, severity: Severity) -> Decision:
        return Decision.parse(self.severity_effects.get(severity.value, "review"), Decision.REVIEW)

    def exception_rule_for(self, code: str) -> ExceptionRule | None:
        for rule in self.exceptions:
            if rule.covers(code):
                return rule
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description, "mode": self.mode,
            "severity_effects": dict(self.severity_effects), "rules": [r.to_dict() for r in self.rules],
            "exceptions": [e.to_dict() for e in self.exceptions],
            "unknown_mandatory_effect": self.unknown_mandatory_effect, "min_coverage": self.min_coverage,
            "decision_valid_hours": self.decision_valid_hours, "model_assist": self.model_assist,
            "external_inference": self.external_inference, "mandatory_overrides": dict(self.mandatory_overrides),
            "require_baseline": self.require_baseline, "require_av_scan": self.require_av_scan,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AssurancePolicy":
        if not isinstance(d, dict):
            raise ValidationFailed("policy must be an object")
        pid = str(d.get("id", "")).strip()
        if not pid:
            raise ValidationFailed("policy.id is required")
        effects = dict(DEFAULT_SEVERITY_EFFECTS)
        effects.update({str(k).lower(): str(v).lower() for k, v in (d.get("severity_effects") or {}).items()})
        return cls(
            id=pid, name=str(d.get("name") or pid), description=str(d.get("description", "")),
            mode=str(d.get("mode", "enforce")), severity_effects=effects,
            rules=[PolicyRule.from_dict(r) for r in _list(d.get("rules"))],
            exceptions=[ExceptionRule.from_dict(e) for e in _list(d.get("exceptions"))],
            unknown_mandatory_effect=str(d.get("unknown_mandatory_effect", "review")),
            min_coverage=float(d.get("min_coverage", 0.95)),
            decision_valid_hours=int(d.get("decision_valid_hours", 24 * 30)),
            model_assist=bool(d.get("model_assist", False)),
            external_inference=bool(d.get("external_inference", False)),
            mandatory_overrides={str(k): bool(v) for k, v in (d.get("mandatory_overrides") or {}).items()},
            require_baseline=bool(d.get("require_baseline", False)),
            require_av_scan=bool(d.get("require_av_scan", False)),
        )
