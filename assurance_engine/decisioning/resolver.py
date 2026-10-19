"""Apply attributable exceptions to reasons. Non-waivable codes are never touched."""

from __future__ import annotations

from datetime import datetime

from ...domain.decisions import Decision, ExceptionGrant, Reason, exception_allowed_for
from ...domain.policies import AssurancePolicy

__all__ = ["apply_exceptions"]


def apply_exceptions(reasons: list[Reason], grants: list[ExceptionGrant], policy: AssurancePolicy,
                     now: datetime) -> tuple[list[Reason], list[str]]:
    """Mark reasons waived when an *active* grant lists the code and the policy permits waiving it."""
    used: list[str] = []
    for r in reasons:
        r.waivable = exception_allowed_for(r.code) and policy.exception_rule_for(r.code) is not None
        if not r.waivable or r.effect == Decision.PASS:
            continue
        for g in grants:
            if g.active(now) and r.code in g.reason_codes:
                r.waived_by = g.id
                if g.id not in used:
                    used.append(g.id)
                break
    return reasons, used
