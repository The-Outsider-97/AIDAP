"""Version lifecycle and publication lint for profiles and policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..data.classification import DataClassification, DestinationClass, SourceClass
from ..data.sensitivity import SensitiveType
from ..decisions.models import Decision
from ..evaluations import CHECK_CATALOG
from .models import AssurancePolicy, IntendedUseProfile
from .regex_guard import check_regex

__all__ = ["VersionStatus", "LintIssue", "lint_profile", "lint_policy", "lint", "blocking"]


class VersionStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


@dataclass
class LintIssue:
    level: str          # "error" | "warning"
    path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "path": self.path, "message": self.message}


def _err(out: list[LintIssue], path: str, msg: str) -> None:
    out.append(LintIssue("error", path, msg))


def _warn(out: list[LintIssue], path: str, msg: str) -> None:
    out.append(LintIssue("warning", path, msg))


def lint_profile(p: IntendedUseProfile) -> list[LintIssue]:
    out: list[LintIssue] = []
    if not p.task:
        _warn(out, "task", "no task is named; reviewers will not see what this profile is for")
    for i, name in enumerate(p.required_checks + p.optional_checks):
        if name not in CHECK_CATALOG:
            _err(out, f"checks[{i}]", f"unknown check '{name}'")
    overlap = set(p.required_checks) & set(p.optional_checks)
    if overlap:
        _err(out, "checks", f"checks listed as both required and optional: {sorted(overlap)}")
    for d in p.destinations:
        try:
            DestinationClass(d)
        except ValueError:
            _err(out, "destinations", f"unknown destination class '{d}'")
    for s in p.source_classes:
        try:
            SourceClass(s)
        except ValueError:
            _err(out, "source_classes", f"unknown source class '{s}'")
    try:
        DataClassification(p.max_classification)
    except ValueError:
        _err(out, "max_classification", f"unknown classification '{p.max_classification}'")
    for t in p.privacy.allowed_types + p.privacy.external_forbidden_types:
        try:
            SensitiveType(t)
        except ValueError:
            _err(out, "privacy", f"unknown sensitive type '{t}'")
    if any(DestinationClass(d).is_external for d in p.destinations if d in DestinationClass._value2member_map_):
        leaked = set(p.privacy.allowed_types) & set(p.privacy.external_forbidden_types)
        if leaked:
            _err(out, "privacy", f"types both allowed and externally forbidden for an external destination: {sorted(leaked)}")
        if "privacy.pii" not in p.required_checks:
            _err(out, "required_checks", "external destinations require the privacy.pii check as mandatory")
        if "privacy.destination" not in p.required_checks:
            _err(out, "required_checks", "external destinations require the privacy.destination check as mandatory")
    for i, rule in enumerate(p.semantic_rules):
        for key in ("forbid_regex", "require_regex"):
            if key in rule:
                reason = check_regex(str(rule[key]))
                if reason:
                    _err(out, f"semantic_rules[{i}].{key}", reason)
    for i, f in enumerate(p.fields):
        if not f.get("name"):
            _err(out, f"fields[{i}]", "field needs a name")
        if f.get("type") not in (None, "string", "number", "integer", "boolean", "date", "any"):
            _err(out, f"fields[{i}].type", f"unsupported type '{f.get('type')}'")
        if "pattern" in f and check_regex(str(f["pattern"])):
            _err(out, f"fields[{i}].pattern", check_regex(str(f["pattern"])) or "")
    if p.freshness_days is not None and p.freshness_days <= 0:
        _err(out, "freshness_days", "must be positive")
    if p.uncertainty not in ("strict", "limited"):
        _err(out, "uncertainty", "must be 'strict' or 'limited'")
    return out


def lint_policy(pol: AssurancePolicy) -> list[LintIssue]:
    out: list[LintIssue] = []
    if pol.mode not in ("enforce", "shadow"):
        _err(out, "mode", "must be 'enforce' or 'shadow'")
    if pol.mode == "shadow":
        _warn(out, "mode", "shadow policies never authorise release")
    for sev, eff in pol.severity_effects.items():
        if eff not in {d.value for d in Decision}:
            _err(out, f"severity_effects.{sev}", f"unknown effect '{eff}'")
    if pol.severity_effects.get("critical") == "pass":
        _err(out, "severity_effects.critical", "critical findings cannot map to PASS")
    if pol.unknown_mandatory_effect not in ("review", "block", "quarantine"):
        _err(out, "unknown_mandatory_effect", "an unresolved mandatory check can never map to PASS")
    if not 0.0 <= pol.min_coverage <= 1.0:
        _err(out, "min_coverage", "must be between 0 and 1")
    if pol.decision_valid_hours <= 0:
        _err(out, "decision_valid_hours", "must be positive")
    ids = [r.id for r in pol.rules]
    if len(ids) != len(set(ids)):
        _err(out, "rules", "duplicate rule ids")
    for r in pol.rules:
        if r.effect == Decision.PASS and r.when.get("severity_min") in ("high", "critical"):
            _warn(out, f"rules.{r.id}", "a PASS rule for high/critical findings weakens the gate; use an exception instead")
        if r.effect == Decision.PASS and (r.when.get("code_prefix", "").startswith("safety.") or r.when.get("category") == "safety"):
            _err(out, f"rules.{r.id}", "safety findings cannot be passed by rule")
    if pol.external_inference and not pol.model_assist:
        _warn(out, "external_inference", "external inference has no effect unless model_assist is enabled")
    for e in pol.exceptions:
        if e.max_days <= 0 or e.max_days > 365:
            _err(out, f"exceptions.{e.id}", "max_days must be between 1 and 365")
        for code in e.codes:
            if code.startswith(("safety.malicious", "privacy.secret", "policy.prohibited")):
                _err(out, f"exceptions.{e.id}", f"'{code}' can never be waived")
    return out


def lint(profile: IntendedUseProfile | None = None, policy: AssurancePolicy | None = None) -> list[LintIssue]:
    out: list[LintIssue] = []
    if profile is not None:
        out += lint_profile(profile)
    if policy is not None:
        out += lint_policy(policy)
    return out


def blocking(issues: list[LintIssue]) -> list[LintIssue]:
    return [i for i in issues if i.level == "error"]
