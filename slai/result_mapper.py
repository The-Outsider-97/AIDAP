"""Translate SLAI agent outputs into AIDAP findings.

Rules that make this safe to trust:
  * SLAI scores are never presented as probabilities: confidence is HEURISTIC with the raw score as a relative value;
  * severity is capped at HIGH - an uncalibrated score may demand a human look (REVIEW) but cannot by itself trigger an
    irreversible disposition; deterministic AIDAP checks own QUARANTINE/BLOCK;
  * raw previews/sanitized text returned by SLAI are NEVER copied into evidence (only paths and counts);
  * baseline-dependent SLAI quality checks are dropped: baselines in AIDAP are proposed and approved by people.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..assurance_engine.evaluators.base import make_finding, pointer
from ..domain.evaluations import Confidence, Finding, Origin, Severity

__all__ = ["map_privacy_identification", "map_quality_decision", "map_safety_assessment", "map_provenance_report",
           "cap_severity", "BASELINE_DEPENDENT"]

BASELINE_DEPENDENT = {"drift", "distribution_drift", "distribution_shift", "relationship_drift", "numeric_correlation",
                      "missingness_correlation", "baseline"}
_SEV = {"info": Severity.INFO, "low": Severity.LOW, "medium": Severity.MEDIUM, "moderate": Severity.MEDIUM,
        "high": Severity.HIGH, "critical": Severity.HIGH, "severe": Severity.HIGH, "block": Severity.HIGH,
        "warn": Severity.LOW, "warning": Severity.LOW}
_CAP = Severity.HIGH


def cap_severity(value: Any, default: Severity = Severity.MEDIUM) -> Severity:
    sev = _SEV.get(str(value).strip().lower(), default)
    return sev if sev <= _CAP else _CAP


def _score(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 1.0 else None


def _slug(value: Any, fallback: str = "finding") -> str:
    s = "".join(c if c.isalnum() else "_" for c in str(value or fallback).lower()).strip("_")
    return (s or fallback)[:48]


def _path(value: Any) -> str:
    p = str(value or "")
    p = p[5:] if p.startswith("root.") else p
    return p[:200] or "input"


# -------------------------------------------------------------------------------------------------- privacy
_CONTEXT_REQUIRED = {k: re.compile(r"birth|dob|born|geburt|naissance|nacimiento") for k in ("date_of_birth", "dob", "birth_date", "birthdate")}
_SPECIAL_CATEGORIES = {"health", "medical", "religion", "religious", "ethnicity", "racial", "political", "sexual_orientation",
                       "biometric", "genetic", "trade_union", "criminal"}


def map_privacy_identification(result: Mapping[str, Any], native_types: set[str]) -> tuple[list[Finding], dict[str, Any]]:
    """``DataID.identify_entities`` output -> findings for entities AIDAP's own detectors did not already report."""
    findings: list[Finding] = []
    corroborated = ignored_context = 0
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for ent in result.get("detected_entities") or []:
        etype = _slug(ent.get("entity_type"), "entity")
        if etype in native_types:                  # AIDAP's own detectors already report this type: corroboration
            corroborated += 1
            continue
        if etype in _CONTEXT_REQUIRED and not _CONTEXT_REQUIRED[etype].search(_path(ent.get("path")).lower()):
            ignored_context += 1                   # a bare date is not a date of birth; require a field-name hint
            continue
        grouped.setdefault((etype, str(ent.get("category", ""))), []).append(ent)
    for (etype, category), ents in grouped.items():
        best = max((e.get("confidence") or 0 for e in ents), default=0)
        sev = cap_severity(ents[0].get("severity"), Severity.MEDIUM)
        findings.append(make_finding(
            "slai.privacy", f"slai.privacy.{etype}", f"SLAI identified possible {etype.replace('_', ' ')} data", sev,
            f"{len(ents)} location(s) flagged as {etype} ({category or 'identifier'}) by SLAI entity identification",
            "A second detector flagged personal data that AIDAP's own patterns did not report.",
            Confidence.heuristic(_score(best), "SLAI entity identification score (uncalibrated)"),
            "Review the flagged fields and redact or remove them if they are personal data.",
            pointers=[pointer(_path(e.get("path"))) for e in ents[:8]], count=len(ents),
            tags=["slai", "privacy"], origin=Origin.SLAI, data={"entity_type": etype, "detectors": sorted(
                {str(e.get("detector", "")) for e in ents})}))
    for attr in result.get("sensitive_attributes") or []:
        name = _slug(attr.get("attribute"), "attribute")
        findings.append(make_finding(
            "slai.privacy", f"slai.privacy.attribute.{name}", f"Sensitive attribute context: {name.replace('_', ' ')}",
            Severity.MEDIUM if name in _SPECIAL_CATEGORIES else Severity.LOW, f"SLAI tagged content near '{_path(attr.get('path'))}' as {name} ({attr.get('reason', '')})",
            "Keyword-level evidence only; it indicates context, not an extracted value.",
            Confidence.heuristic(_score(attr.get("confidence")), "SLAI keyword/context score (uncalibrated)"),
            "Confirm whether the field may be used for the stated purpose.",
            pointers=[pointer(_path(attr.get("path")))], tags=["slai", "privacy", "attribute"], origin=Origin.SLAI))
    metrics = {"slai_entity_count": result.get("entity_count"), "corroborated_by_aidap": corroborated, "ignored_without_context": ignored_context,
               "slai_decision": result.get("decision"), "slai_sensitivity": result.get("sensitivity_score"),
               "slai_uncertainty": result.get("uncertainty_score")}
    return findings, metrics


# -------------------------------------------------------------------------------------------------- quality
_VERDICT_MIN = {"reject": Severity.HIGH, "block": Severity.HIGH, "quarantine": Severity.HIGH, "review": Severity.MEDIUM,
                "warn": Severity.LOW}


def map_quality_decision(decision: Mapping[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    dropped_baseline = 0
    for sub, res in (decision.get("subsystem_results") or {}).items():
        if not isinstance(res, Mapping):
            continue
        sub_verdict = str(res.get("verdict", "")).lower()
        for raw in res.get("findings") or []:
            if not isinstance(raw, Mapping):
                continue
            code = _slug(raw.get("check") or raw.get("rule_id") or raw.get("type") or raw.get("code") or raw.get("flag"),
                         "issue")
            if any(b in code for b in BASELINE_DEPENDENT):
                dropped_baseline += 1
                continue
            sev = cap_severity(raw.get("severity"), _VERDICT_MIN.get(sub_verdict, Severity.MEDIUM))
            where = raw.get("field") or raw.get("column") or raw.get("path") or raw.get("feature")
            msg = str(raw.get("message") or raw.get("description") or raw.get("detail") or code.replace("_", " "))[:400]
            findings.append(make_finding(
                "slai.quality", f"slai.quality.{_slug(sub)}.{code}", f"SLAI {sub} check: {code.replace('_', ' ')}", sev,
                msg, "SLAI's quality subsystem flagged this; AIDAP has not independently re-derived it.",
                Confidence.heuristic(_score(raw.get("score") or raw.get("confidence")), "SLAI quality score (uncalibrated)"),
                str(raw.get("remediation") or raw.get("recommendation") or "Inspect the cited field and correct the source.")[:300],
                pointers=[pointer(f"records.{where}")] if where else [], tags=["slai", "quality", _slug(sub)],
                origin=Origin.SLAI))
    metrics = {"slai_verdict": decision.get("verdict"), "slai_batch_score": decision.get("batch_score"),
               "subsystem_verdicts": decision.get("subsystem_verdicts"), "baseline_dependent_dropped": dropped_baseline,
               "slai_flags": list(decision.get("flags") or [])[:20]}
    return findings, metrics


# -------------------------------------------------------------------------------------------------- safety
def map_safety_assessment(result: Mapping[str, Any]) -> tuple[list[Finding], dict[str, Any], float]:
    """Returns ``(findings, metrics, coverage)``. Degraded SLAI components reduce coverage; they never read as safe."""
    findings: list[Finding] = []
    risk = _score(result.get("risk_score"))
    for b in result.get("blockers") or []:
        findings.append(make_finding(
            "slai.safety", f"slai.safety.blocker.{_slug(b)}", "SLAI safety agent raised a blocker", Severity.HIGH,
            f"Blocker: {str(b)[:300]}", "A SLAI safety component judged the content unsafe to pass on.",
            Confidence.heuristic(risk, "SLAI aggregate risk score (uncalibrated)"),
            "Have a security reviewer inspect the content before any release.", tags=["slai", "safety"],
            origin=Origin.SLAI))
    for w in result.get("warnings") or []:
        findings.append(make_finding(
            "slai.safety", f"slai.safety.warning.{_slug(w)}", "SLAI safety agent warning", Severity.LOW,
            f"Warning: {str(w)[:300]}", "Advisory signal from SLAI safety analysis.",
            Confidence.heuristic(risk, "SLAI aggregate risk score (uncalibrated)"),
            "Review if the destination is sensitive.", tags=["slai", "safety"], origin=Origin.SLAI))
    for v in result.get("constitutional_violations") or []:
        label = v.get("rule") if isinstance(v, Mapping) else v
        findings.append(make_finding(
            "slai.safety", f"slai.safety.policy.{_slug(label)}", "SLAI policy violation", Severity.HIGH,
            f"Violation: {str(label)[:300]}", "Content conflicts with a configured SLAI safety principle.",
            Confidence.heuristic(risk, "SLAI aggregate risk score (uncalibrated)"),
            "Remove or rewrite the flagged content.", tags=["slai", "safety"], origin=Origin.SLAI))
    degraded = list(result.get("degraded_components") or [])
    coverage = 1.0 if not degraded else max(0.0, 1.0 - 0.25 * len(degraded))
    metrics = {"slai_decision": result.get("decision"), "slai_risk_score": risk, "slai_risk_level": result.get("risk_level"),
               "degraded_components": degraded}
    return findings, metrics, coverage


# -------------------------------------------------------------------------------------------------- provenance
def map_provenance_report(report: Mapping[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    gaps = list(report.get("gaps") or report.get("missing") or report.get("warnings") or [])
    for g in gaps[:20]:
        label = g.get("field") if isinstance(g, Mapping) else g
        findings.append(make_finding(
            "slai.provenance", f"slai.provenance.gap.{_slug(label)}", "Lineage record is incomplete", Severity.LOW,
            f"SLAI reproducibility report lists a gap: {str(label)[:200]}",
            "Incomplete lineage limits how well this input can be reproduced or traced.",
            Confidence.heuristic(None, "SLAI reproducibility report"), "Record the missing source or transformation step.",
            tags=["slai", "provenance"], origin=Origin.SLAI))
    return findings, {"reproducible": report.get("reproducible"), "gap_count": len(gaps)}
