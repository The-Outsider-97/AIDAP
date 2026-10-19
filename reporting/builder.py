"""Assemble the run report (``aidap.report/1``) from stored records. Pure: no I/O, no SLAI, no content previews."""

from __future__ import annotations

from typing import Any

from ..contracts.versions import REPORT_SCHEMA
from ..domain.decisions import FitnessDecision
from ..domain.utils.domain_helpers import parse_iso

__all__ = ["build_report", "REPORT_NOTES"]

_SEV = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

REPORT_NOTES = [
    "A decision applies to one exact input, under one profile version and one policy version, at one point in time.",
    "Confidence is reported as deterministic, heuristic or unknown. No confidence here is a calibrated probability.",
    "Digests identify content and detect change; they do not prove authenticity or authorship.",
    "A check that did not run is shown as unknown or not evaluated. It is never counted as passed.",
    "Model-assisted findings can raise a decision to REVIEW at most; they can never block or quarantine on their own.",
]


def build_report(*, run: dict[str, Any], decision: dict[str, Any], artifacts: dict[str, Any], evidence: dict[str, Any],
                 grants: list[dict[str, Any]], history: list[dict[str, Any]], project: dict[str, Any],
                 generated_at: str) -> dict[str, Any]:
    fd = FitnessDecision.from_dict(decision)
    now = parse_iso(generated_at)
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for cid, r in sorted(artifacts.get("results", {}).items()):
        checks.append({"check_id": cid, "status": r["status"], "evaluator": r.get("evaluator", ""), "origin": r.get("origin", "native"),
                       "mandatory": r.get("mandatory", False), "coverage": r.get("coverage"), "findings": len(r.get("findings", [])),
                       "unknown_reason": r.get("unknown_reason"), "message": r.get("message", "")})
        findings.extend(r.get("findings", []))
    findings.sort(key=lambda f: (-_SEV.get(f["severity"], 0), f["code"]))
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    unresolved = [c["check_id"] for c in checks if c["status"] in ("unknown", "not_evaluated", "error")]
    return {
        "schema": REPORT_SCHEMA, "generated_at": generated_at,
        "run": {k: run.get(k) for k in ("id", "project_id", "filename", "label", "created_at", "finished_at", "created_by",
                                         "profile_id", "profile_version", "policy_id", "policy_version", "destination_id",
                                         "input_digest", "size", "source", "classification", "source_class", "state", "version_no",
                                         "parent_run_id", "plan_id")} | {"project_name": project.get("name", "")},
        "decision": {
            "id": fd.id, "decision": fd.decision.value, "status": fd.status.value, "disposition": fd.disposition.value,
            "release_authorized": fd.release_authorized(now, None) if now else False, "shadow": fd.shadow,
            "summary": fd.rationale.summary, "next_action": fd.rationale.next_action, "steps": [s.to_dict() for s in fd.rationale.steps],
            "reasons": [r.to_dict() for r in fd.reasons], "policy_ref": fd.policy_ref, "profile_ref": fd.profile_ref,
            "input_digest": fd.input_digest, "released_digest": fd.released_digest,
            "expires_at": decision.get("expires_at"), "decided_by": fd.decided_by, "exception_ids": fd.exception_ids,
            "created_at": decision.get("created_at"), "score": fd.score},
        "coverage": {**(fd.coverage or {}), "unresolved_checks": unresolved},
        "confidence": artifacts.get("confidence"), "severity_counts": counts, "checks": checks, "findings": findings,
        "exceptions": [{k: g.get(k) for k in ("id", "reason_codes", "granted_by", "granted_role", "justification", "created_at",
                                               "expires_at", "revoked")} for g in grants],
        "history": [{"id": h["id"], "decision": h["decision"], "status": h["status"], "decided_by": h.get("decided_by", ""),
                     "created_at": h.get("created_at"), "supersedes": h.get("supersedes")} for h in history],
        "evidence": {"seal": evidence.get("seal", ""), "bundle_id": evidence.get("bundle_id", ""),
                     "findings": evidence.get("findings", len(findings))},
        "notes": REPORT_NOTES,
    }
