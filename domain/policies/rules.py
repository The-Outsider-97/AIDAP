"""Rule matching: the pure function that maps a finding to a policy effect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..data.classification import DataClassification, DestinationClass
from ..decisions.models import Decision
from ..evaluations.models import Finding, Origin
from ..evaluations.severity import Severity
from .models import AssurancePolicy, PolicyRule

__all__ = ["MatchContext", "rule_matches", "resolve_effect"]


@dataclass(frozen=True)
class MatchContext:
    destination: DestinationClass = DestinationClass.LOCAL_INDEX
    classification: DataClassification = DataClassification.INTERNAL
    profile_id: str = ""
    source_class: str = "unknown"


def rule_matches(rule: PolicyRule, finding: Finding, ctx: MatchContext) -> bool:
    w: dict[str, Any] = rule.when
    if not w:
        return False
    if "check_id" in w and finding.check_id != w["check_id"]:
        return False
    if "code" in w and finding.code != w["code"]:
        return False
    if "code_prefix" in w and not finding.code.startswith(str(w["code_prefix"])):
        return False
    if "category" in w and finding.category.value != w["category"]:
        return False
    if "origin" in w and finding.origin.value != w["origin"]:
        return False
    if "severity_min" in w and finding.severity < Severity.parse(w["severity_min"]):
        return False
    if "severity" in w and finding.severity != Severity.parse(w["severity"]):
        return False
    if "destination" in w and ctx.destination.value != w["destination"]:
        return False
    if "destination_external" in w and bool(w["destination_external"]) != ctx.destination.is_external:
        return False
    if "classification_min" in w and ctx.classification.rank < DataClassification.parse(w["classification_min"]).rank:
        return False
    if "profile" in w and ctx.profile_id != w["profile"]:
        return False
    if "tag" in w and w["tag"] not in finding.tags:
        return False
    return True


def resolve_effect(policy: AssurancePolicy, finding: Finding, ctx: MatchContext) -> tuple[Decision, str | None]:
    """First matching explicit rule wins; otherwise severity mapping.

    Safeguards that no policy can remove:
    * model-origin findings never exceed REVIEW (they are not authoritative);
    * a finding never *lowers* the baseline implied by its own severity mapping
      when the rule effect is PASS and the finding is mandatory-critical.
    """
    effect: Decision | None = None
    rule_id: str | None = None
    for rule in policy.rules:
        if rule_matches(rule, finding, ctx):
            effect, rule_id = rule.effect, rule.id
            break
    if effect is None:
        effect = policy.effect_for_severity(finding.severity)
    if finding.origin == Origin.MODEL and effect.rank > Decision.REVIEW.rank:
        effect = Decision.REVIEW
    return effect, rule_id
